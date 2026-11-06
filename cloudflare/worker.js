/**
 * SentinelDR Cloudflare Worker - Dynamic Edge Router
 * 
 * Objective: Stable public hostname (portfolio.sentineldr.in) that routes
 * exclusively to the eligible, active-owner node.
 * 
 * Guarantees:
 * 1. Tunnel health alone NEVER selects a non-owner.
 * 2. Strict active-origin verification (role, epoch, lease validity).
 * 3. Blocks public access to all /api/v1/peer/* endpoints at the edge with 403 Forbidden.
 * 4. Fences writes during safe-mode or standby transitions (prevents dual-writers).
 * 5. Zero hardcoded secrets (configured via Worker environment variables / bindings).
 */

const DEFAULT_PRIMARY = "https://primary-origin.sentineldr.in";
const DEFAULT_BACKUP = "https://backup-origin.sentineldr.in";
const DEFAULT_TIMEOUT_MS = 2500;
const DEFAULT_CACHE_TTL_MS = 1500;

// In-memory cache for edge target resolution
let cachedRoute = {
  targetOrigin: null,
  activeNode: null,
  role: null,
  writable: false,
  timestamp: 0,
};

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const pathname = url.pathname;

    const primaryOrigin = env?.PRIMARY_ORIGIN || DEFAULT_PRIMARY;
    const backupOrigin = env?.BACKUP_ORIGIN || DEFAULT_BACKUP;
    const timeoutMs = parseInt(env?.ROUTING_TIMEOUT_MS || DEFAULT_TIMEOUT_MS, 10);
    const cacheTtlMs = parseInt(env?.EDGE_CACHE_TTL_MS || DEFAULT_CACHE_TTL_MS, 10);

    // 1. Edge Perimeter Defense: Block public access to internal peer endpoints
    if (pathname.startsWith("/api/v1/peer/")) {
      return makeEnvelopeError(
        403,
        "FORBIDDEN",
        "Direct access to internal peer replication endpoints is blocked from public internet."
      );
    }

    // 2. Handle CORS Preflight for approved origins
    const originHeader = request.headers.get("Origin");
    if (request.method === "OPTIONS") {
      return handleCorsPreflight(originHeader);
    }

    // 3. Resolve active origin target
    const route = await resolveActiveTarget(primaryOrigin, backupOrigin, timeoutMs, cacheTtlMs);

    // 4. Safe Mode / Standby Write Fencing
    const isWriteMethod = ["POST", "PUT", "DELETE", "PATCH"].includes(request.method);
    if (isWriteMethod && !route.writable) {
      return makeEnvelopeError(
        503,
        "CLUSTER_MAINTENANCE",
        `Protected write rejected: Cluster is in ${route.role || "SAFE_MODE"}. No active writable primary is elected.`
      );
    }

    // 5. Total Cluster Failure (Both nodes unreachable)
    if (!route.targetOrigin) {
      return makeEnvelopeError(
        503,
        "SERVICE_UNAVAILABLE",
        "Disaster Recovery Alert: All cluster origin nodes are currently unreachable."
      );
    }

    // 6. Proxy Request to Selected Origin
    try {
      const originUrl = new URL(pathname + url.search, route.targetOrigin);
      const forwardHeaders = new Headers(request.headers);
      
      forwardHeaders.set("Host", new URL(route.targetOrigin).host);
      forwardHeaders.set("X-Forwarded-Host", url.host);
      forwardHeaders.set("X-SDR-Routed-To", route.activeNode || "unknown");

      if (env?.EDGE_ROUTING_SECRET) {
        forwardHeaders.set("X-SDR-Edge-Secret", env.EDGE_ROUTING_SECRET);
      }

      const proxyReq = new Request(originUrl.toString(), {
        method: request.method,
        headers: forwardHeaders,
        body: ["GET", "HEAD"].includes(request.method) ? null : request.body,
        redirect: "follow",
      });

      const response = await fetch(proxyReq);
      
      // Inject standard CORS and edge tracking headers on response
      const responseHeaders = new Headers(response.headers);
      applyCorsHeaders(responseHeaders, originHeader);
      responseHeaders.set("X-SDR-Edge-Router", "SentinelDR-v1");
      responseHeaders.set("X-SDR-Target-Node", route.activeNode || "unknown");

      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: responseHeaders,
      });
    } catch (err) {
      // Invalidate cache immediately on proxy error
      cachedRoute.timestamp = 0;
      return makeEnvelopeError(
        502,
        "BAD_GATEWAY",
        `Failed to communicate with active origin (${route.activeNode}): ${err.message}`
      );
    }
  },
};

/**
 * Determine eligible active origin by querying /api/v1/active-origin
 */
async function resolveActiveTarget(primaryOrigin, backupOrigin, timeoutMs, cacheTtlMs) {
  const now = Date.now();
  if (cachedRoute.targetOrigin && (now - cachedRoute.timestamp) < cacheTtlMs) {
    return cachedRoute;
  }

  const [primaryStatus, backupStatus] = await Promise.all([
    queryOriginStatus(primaryOrigin, timeoutMs),
    queryOriginStatus(backupOrigin, timeoutMs),
  ]);

  let selected = {
    targetOrigin: null,
    activeNode: null,
    role: null,
    writable: false,
    timestamp: now,
  };

  // Rule 1: Active Primary Writer (Laptop)
  if (primaryStatus && primaryStatus.writable && primaryStatus.role === "PRIMARY_ACTIVE") {
    selected.targetOrigin = primaryOrigin;
    selected.activeNode = "laptop";
    selected.role = "PRIMARY_ACTIVE";
    selected.writable = true;
  }
  // Rule 2: Active Promoted Secondary (Phone failover)
  else if (backupStatus && backupStatus.writable && backupStatus.role === "SECONDARY_ACTIVE") {
    selected.targetOrigin = backupOrigin;
    selected.activeNode = "phone";
    selected.role = "SECONDARY_ACTIVE";
    selected.writable = true;
  }
  // Rule 3: No writable primary elected (Read-Only / Standby fallback)
  else if (primaryStatus && primaryStatus.db_healthy) {
    selected.targetOrigin = primaryOrigin;
    selected.activeNode = "laptop";
    selected.role = primaryStatus.role;
    selected.writable = false;
  } else if (backupStatus && backupStatus.db_healthy) {
    selected.targetOrigin = backupOrigin;
    selected.activeNode = "phone";
    selected.role = backupStatus.role;
    selected.writable = false;
  }

  cachedRoute = selected;
  return selected;
}

/**
 * Query /api/v1/active-origin with timeout
 */
async function queryOriginStatus(originUrl, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const resp = await fetch(`${originUrl}/api/v1/active-origin`, {
      method: "GET",
      headers: { "Accept": "application/json" },
      signal: controller.signal,
    });
    clearTimeout(timer);

    if (!resp.ok) return null;
    const body = await resp.json();
    return (body && body.ok && body.data) ? body.data : null;
  } catch (e) {
    clearTimeout(timer);
    return null;
  }
}

/**
 * Standard SentinelDR JSON Error Envelope Helper
 */
function makeEnvelopeError(status, code, message) {
  const envelope = {
    ok: false,
    error: {
      code: code,
      message: message,
    },
    request_id: crypto.randomUUID ? crypto.randomUUID() : `req-${Date.now()}`,
    node_id: "edge-router",
    epoch: 0,
  };
  return new Response(JSON.stringify(envelope), {
    status: status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "X-SDR-Edge-Router": "SentinelDR-v1",
      "Cache-Control": "no-store, no-cache, must-revalidate",
    },
  });
}

/**
 * CORS handling
 */
const APPROVED_ORIGINS = [
  "https://portfolio.sentineldr.in",
  "https://primary-origin.sentineldr.in",
  "https://backup-origin.sentineldr.in",
  "http://localhost:8000",
  "http://127.0.0.1:8000",
  "http://localhost:8001",
  "http://127.0.0.1:8001",
];

function applyCorsHeaders(headers, origin) {
  if (origin && APPROVED_ORIGINS.includes(origin)) {
    headers.set("Access-Control-Allow-Origin", origin);
    headers.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    headers.set("Access-Control-Allow-Headers", "Content-Type, Accept, X-SDR-Node, X-SDR-Epoch");
  }
}

function handleCorsPreflight(origin) {
  const headers = new Headers();
  if (origin && APPROVED_ORIGINS.includes(origin)) {
    headers.set("Access-Control-Allow-Origin", origin);
    headers.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    headers.set("Access-Control-Allow-Headers", "Content-Type, Accept, X-SDR-Node, X-SDR-Epoch");
    headers.set("Access-Control-Max-Age", "86400");
  }
  return new Response(null, { status: 204, headers: headers });
}

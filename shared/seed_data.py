"""
SentinelDR - Shared Seed Data
Standard library only (runtime-neutral for Laptop & Phone).
Derived directly from the original portfolio.html structure.
"""

PROFILE_SEED = {
    "id": "default_profile",
    "name": "Your Name",
    "headline": "BCA Student | Cybersecurity Enthusiast | Cloud Architecture Learner",
    "bio_primary": "Passionate about cybersecurity, technology, and building innovative solutions.",
    "bio_secondary": (
        "I am a BCA student specializing in Cloud Architecture and Cybersecurity. "
        "I am interested in ethical hacking, vulnerability assessment, penetration testing, "
        "and cloud security. I enjoy learning new technologies and developing practical projects."
    ),
    "cta_text": "Explore My Work",
}

SKILLS_SEED = [
    {
        "id": "skill_programming",
        "category": "Programming",
        "items": ["Python", "Java", "C", "C++"],
        "display_order": 1,
    },
    {
        "id": "skill_cybersecurity",
        "category": "Cybersecurity",
        "items": ["Nmap", "WPScan", "Vulnerability Scanning"],
        "display_order": 2,
    },
    {
        "id": "skill_database",
        "category": "Database",
        "items": ["MySQL"],
        "display_order": 3,
    },
    {
        "id": "skill_os",
        "category": "Operating Systems",
        "items": ["Linux", "Windows"],
        "display_order": 4,
    },
]

PROJECTS_SEED = [
    {
        "id": "proj_vuln_scanner",
        "title": "Vulnerability Scanner",
        "description": "A project focused on identifying security vulnerabilities in systems and applications.",
        "link": "https://github.com/yourusername/vulnerability-scanner",
        "display_order": 1,
    },
    {
        "id": "proj_task_mgr",
        "title": "Task Management System",
        "description": "A system designed to manage tasks, monitor progress and improve productivity.",
        "link": "https://github.com/yourusername/task-manager",
        "display_order": 2,
    },
    {
        "id": "proj_phishguard",
        "title": "PhishGuard",
        "description": "A project focused on detecting suspicious and potentially malicious URLs.",
        "link": "https://github.com/yourusername/phishguard",
        "display_order": 3,
    },
]

EXPERIENCE_SEED = [
    {
        "id": "exp_cybersecurity_intern",
        "role": "Cybersecurity Intern",
        "company": "SecureCloud Systems",
        "duration": "2025 - Present",
        "description": "Assisting in network penetration tests, vulnerability assessments, and security scanning.",
        "display_order": 1,
    }
]

EDUCATION_SEED = [
    {
        "id": "edu_bca",
        "degree": "Bachelor of Computer Applications (BCA)",
        "institution": "University School of Information Technology",
        "duration": "2023 - 2026",
        "details": "Specializing in Cloud Architecture and Cybersecurity.",
        "display_order": 1,
    }
]

CERTIFICATIONS_SEED = [
    {
        "id": "cert_ceh_foundations",
        "name": "Certified Ethical Hacker (CEH) Foundations",
        "issuer": "Cybersecurity Council",
        "issue_date": "2025",
        "credential_id": "CEH-FD-89420",
        "display_order": 1,
    }
]

CONTACT_SEED = {
    "id": "default_contact",
    "email": "yourmail@gmail.com",
    "linkedin": "linkedin.com/in/yourprofile",
    "github": "github.com/yourusername",
}

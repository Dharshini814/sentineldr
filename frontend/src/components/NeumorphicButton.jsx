import React from 'react';

export function NeumorphicButton({ 
  label, 
  onClick, 
  variant = 'primary', 
  disabled = false, 
  loading = false, 
  icon = null,
  size = 'md',
  className = ''
}) {
  const baseClasses = 'neumorphic-btn border border-sentineldr-purple-primary/20 font-medium transition-all duration-200 flex items-center justify-center gap-2';
  
  const sizeClasses = {
    sm: 'px-3 py-2 text-sm rounded-lg',
    md: 'px-4 py-3 text-sm rounded-xl', 
    lg: 'px-6 py-4 text-base rounded-xl'
  };
  
  const variantClasses = {
    primary: 'text-sentineldr-text-primary hover:text-sentineldr-purple-light',
    danger: 'text-sentineldr-critical hover:text-red-400',
    success: 'text-sentineldr-success hover:text-green-400',
    ghost: 'text-sentineldr-text-secondary hover:text-sentineldr-text-primary'
  };
  
  const handleClick = (e) => {
    if (disabled || loading) return;
    onClick?.(e);
  };
  
  return (
    <button
      className={`
        ${baseClasses}
        ${sizeClasses[size]}
        ${variantClasses[variant]}
        ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
        ${className}
      `}
      onClick={handleClick}
      disabled={disabled || loading}
    >
      {loading ? (
        <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
      ) : icon ? (
        <span className="text-lg">{icon}</span>
      ) : null}
      
      {label && (
        <span className={loading ? 'opacity-70' : ''}>
          {label}
        </span>
      )}
    </button>
  );
}
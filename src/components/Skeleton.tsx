/**
 * Skeleton Loading Components
 * Notion-style loading placeholders
 */

import React from 'react';

interface SkeletonProps {
  width?: string | number;
  height?: string | number;
  borderRadius?: string | number;
  className?: string;
}

export const Skeleton: React.FC<SkeletonProps> = ({ 
  width = '100%', 
  height = 16, 
  borderRadius = 4,
  className = ''
}) => (
  <div 
    className={`skeleton ${className}`}
    style={{ 
      width: typeof width === 'number' ? `${width}px` : width,
      height: typeof height === 'number' ? `${height}px` : height,
      borderRadius: typeof borderRadius === 'number' ? `${borderRadius}px` : borderRadius,
    }}
  />
);

export const SkeletonText: React.FC<{ lines?: number; className?: string }> = ({ lines = 3, className = '' }) => (
  <div className={`skeleton-text ${className}`}>
    {Array.from({ length: lines }).map((_, i) => (
      <Skeleton 
        key={i} 
        width={i === lines - 1 ? '60%' : '100%'} 
        height={14}
      />
    ))}
  </div>
);

export const SkeletonAvatar: React.FC<{ size?: number }> = ({ size = 40 }) => (
  <Skeleton width={size} height={size} borderRadius="50%" />
);

export const SkeletonCard: React.FC<{ className?: string }> = ({ className = '' }) => (
  <div className={`skeleton-card ${className}`}>
    <div className="skeleton-card-header">
      <SkeletonAvatar size={36} />
      <div className="skeleton-card-title">
        <Skeleton width="60%" height={14} />
        <Skeleton width="40%" height={12} />
      </div>
    </div>
    <SkeletonText lines={2} />
  </div>
);

export const SkeletonTable: React.FC<{ rows?: number; cols?: number }> = ({ rows = 5, cols = 4 }) => (
  <div className="skeleton-table">
    <div className="skeleton-table-header">
      {Array.from({ length: cols }).map((_, i) => (
        <Skeleton key={i} width={`${100 / cols}%`} height={16} />
      ))}
    </div>
    {Array.from({ length: rows }).map((_, rowIndex) => (
      <div key={rowIndex} className="skeleton-table-row">
        {Array.from({ length: cols }).map((_, colIndex) => (
          <Skeleton key={colIndex} width={`${100 / cols}%`} height={14} />
        ))}
      </div>
    ))}
  </div>
);

export const SkeletonMessage: React.FC<{ isOutbound?: boolean }> = ({ isOutbound = false }) => (
  <div className={`skeleton-message ${isOutbound ? 'outbound' : 'inbound'}`}>
    <Skeleton width={isOutbound ? '60%' : '70%'} height={40} borderRadius={12} />
  </div>
);

export const SkeletonContact: React.FC = () => (
  <div className="skeleton-contact">
    <SkeletonAvatar size={44} />
    <div className="skeleton-contact-info">
      <Skeleton width="70%" height={14} />
      <Skeleton width="50%" height={12} />
    </div>
  </div>
);

export const SkeletonStat: React.FC = () => (
  <div className="skeleton-stat">
    <Skeleton width={60} height={36} />
    <Skeleton width={80} height={12} />
  </div>
);

// CSS styles (add to your global CSS or use styled-jsx)

export default Skeleton;

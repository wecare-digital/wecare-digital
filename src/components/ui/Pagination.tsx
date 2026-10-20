/**
 * Reusable Pagination Component
 */

import React from 'react';

interface PaginationProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  showInfo?: boolean;
}

const Pagination: React.FC<PaginationProps> = ({
  currentPage,
  totalPages,
  onPageChange,
  showInfo = true,
}) => {
  const pages = Math.max(1, totalPages);

  const btnStyle = (disabled: boolean): React.CSSProperties => ({
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    width: '44px', height: '44px', minWidth: '44px', minHeight: '44px',
    background: disabled ? '#f9fafb' : '#f5f5f5',
    border: `1px solid ${disabled ? '#e5e7eb' : '#e5e5e5'}`,
    borderRadius: '6px', fontSize: '12px',
    color: disabled ? '#9ca3af' : '#000',
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.4 : 1,
    transition: 'all 0.15s ease',
  });

  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', flexWrap: 'wrap' }}>
      <button aria-label="First page" onClick={() => onPageChange(1)} disabled={currentPage === 1} style={btnStyle(currentPage === 1)}>««</button>
      <button aria-label="Previous page" onClick={() => onPageChange(currentPage - 1)} disabled={currentPage === 1} style={btnStyle(currentPage === 1)}>‹</button>
      {showInfo && <span style={{ fontSize: '12px', color: '#374151', padding: '0 8px', fontWeight: 500 }}>Page {currentPage} of {pages}</span>}
      <button aria-label="Next page" onClick={() => onPageChange(currentPage + 1)} disabled={currentPage >= pages} style={btnStyle(currentPage >= pages)}>›</button>
      <button aria-label="Last page" onClick={() => onPageChange(pages)} disabled={currentPage >= pages} style={btnStyle(currentPage >= pages)}>»»</button>
    </div>
  );
};

export default Pagination;

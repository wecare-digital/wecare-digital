/**
 * Simple Chart Components
 * CSS-based charts for dashboard analytics
 */

import React from 'react';

import DateField from './ui/DateField';

// Bar Chart
interface BarChartProps {
  data: { label: string; value: number; color?: string }[];
  title?: string;
  maxValue?: number;
  height?: number;
}

export const BarChart: React.FC<BarChartProps> = ({ data, title, maxValue, height = 150 }) => {
  const max = maxValue || Math.max(...data.map(d => d.value), 1);
  
  return (
    <div className="chart-container">
      {title && <div className="chart-title">{title}</div>}
      <div className="bar-chart" style={{ height }}>
        {data.map((item, index) => (
          <div key={index} className="bar-chart-item">
            <div className="bar-chart-value">{item.value}</div>
            <div 
              className="bar-chart-bar"
              style={{ 
                height: `${(item.value / max) * 100}%`,
                background: item.color || '#000',
              }}
            />
            <div className="bar-chart-label">{item.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
};

// Donut Chart
interface DonutChartProps {
  value: number;
  total: number;
  label?: string;
  color?: string;
  size?: number;
}

export const DonutChart: React.FC<DonutChartProps> = ({ 
  value, 
  total, 
  label, 
  color = '#000',
  size = 120 
}) => {
  const percentage = total > 0 ? (value / total) * 100 : 0;
  const strokeWidth = 12;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (percentage / 100) * circumference;

  return (
    <div className="donut-chart-wrapper">
      <svg width={size} height={size} className="donut-chart-svg">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="#e5e7eb"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: 'stroke-dashoffset 0.5s ease' }}
        />
      </svg>
      <div className="donut-chart-center">
        <div className="donut-chart-value">{Math.round(percentage)}%</div>
        {label && <div className="donut-chart-label">{label}</div>}
      </div>

      <style jsx>{`
        .donut-chart-wrapper {
          position: relative;
          display: inline-block;
        }
        .donut-chart-svg {
          display: block;
        }
        .donut-chart-center {
          position: absolute;
          top: 50%;
          left: 50%;
          transform: translate(-50%, -50%);
          text-align: center;
        }
        .donut-chart-value {
          font-size: 24px;
          font-weight: 700;
          color: #1f2937;
        }
        .donut-chart-label {
          font-size: 11px;
          color: #6b7280;
          margin-top: 2px;
        }
      `}</style>
    </div>
  );
};

// Line Sparkline
interface SparklineProps {
  data: number[];
  color?: string;
  width?: number;
  height?: number;
}

export const Sparkline: React.FC<SparklineProps> = ({ 
  data, 
  color = '#000',
  width = 100,
  height = 30 
}) => {
  if (data.length < 2) return null;
  
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  
  const points = data.map((value, index) => {
    const x = (index / (data.length - 1)) * width;
    const y = height - ((value - min) / range) * height;
    return `${x},${y}`;
  }).join(' ');

  return (
    <svg width={width} height={height} className="sparkline">
      <polyline
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
};

// Progress Bar
interface ProgressBarProps {
  value: number;
  max: number;
  label?: string;
  color?: string;
  showPercentage?: boolean;
}

export const ProgressBar: React.FC<ProgressBarProps> = ({ 
  value, 
  max, 
  label,
  color = '#000',
  showPercentage = true 
}) => {
  const percentage = max > 0 ? Math.min((value / max) * 100, 100) : 0;

  return (
    <div className="progress-bar-wrapper">
      {label && (
        <div className="progress-bar-header">
          <span className="progress-bar-label">{label}</span>
          {showPercentage && <span className="progress-bar-percentage">{Math.round(percentage)}%</span>}
        </div>
      )}
      <div className="progress-bar-track">
        <div 
          className="progress-bar-fill"
          style={{ width: `${percentage}%`, background: color }}
        />
      </div>

      <style jsx>{`
        .progress-bar-wrapper {
          width: 100%;
        }
        .progress-bar-header {
          display: flex;
          justify-content: space-between;
          margin-bottom: 6px;
        }
        .progress-bar-label {
          font-size: 13px;
          color: rgba(0, 0, 0, 0.54);
        }
        .progress-bar-percentage {
          font-size: 13px;
          font-weight: 600;
          color: #1f2937;
        }
        .progress-bar-track {
          height: 8px;
          background: #e5e7eb;
          border-radius: 4px;
          overflow: hidden;
        }
        .progress-bar-fill {
          height: 100%;
          border-radius: 4px;
          transition: width 0.3s ease;
        }
      `}</style>
    </div>
  );
};

// Stats Mini Card
interface StatsMiniProps {
  label: string;
  value: string | number;
  change?: number;
  icon?: string;
}

export const StatsMini: React.FC<StatsMiniProps> = ({ label, value, change, icon }) => {
  const isPositive = change && change > 0;
  const isNegative = change && change < 0;

  return (
    <div className="stats-mini">
      {icon && <span className="stats-mini-icon">{icon}</span>}
      <div className="stats-mini-content">
        <div className="stats-mini-value">{value}</div>
        <div className="stats-mini-label">{label}</div>
      </div>
      {change !== undefined && (
        <div className={`stats-mini-change ${isPositive ? 'positive' : ''} ${isNegative ? 'negative' : ''}`}>
          {isPositive ? '↑' : isNegative ? '↓' : '→'} {Math.abs(change)}%
        </div>
      )}

      <style jsx>{`
        .stats-mini {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px 16px;
          background: #fff;
          border-radius: 10px;
          border: 1px solid #e5e7eb;
        }
        .stats-mini-icon {
          font-size: 24px;
        }
        .stats-mini-content {
          flex: 1;
        }
        .stats-mini-value {
          font-size: 20px;
          font-weight: 700;
          color: #1f2937;
        }
        .stats-mini-label {
          font-size: 12px;
          color: #6b7280;
        }
        .stats-mini-change {
          font-size: 12px;
          font-weight: 600;
          padding: 4px 8px;
          border-radius: 6px;
          background: #f3f4f6;
          color: #6b7280;
        }
        .stats-mini-change.positive {
          background: #f9fafb;
          color: #0f2a1d;
        }
        .stats-mini-change.negative {
          background: #f9fafb;
          color: #0f2a1d;
        }
      `}</style>
    </div>
  );
};

// Date Range Picker
interface DateRangePickerProps {
  startDate: string;
  endDate: string;
  onStartChange: (date: string) => void;
  onEndChange: (date: string) => void;
  presets?: { label: string; days: number }[];
}

export const DateRangePicker: React.FC<DateRangePickerProps> = ({
  startDate,
  endDate,
  onStartChange,
  onEndChange,
  presets = [
    { label: '7D', days: 7 },
    { label: '30D', days: 30 },
    { label: '90D', days: 90 },
  ]
}) => {
  const setPreset = (days: number) => {
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - days);
    onStartChange(start.toISOString().split('T')[0]);
    onEndChange(end.toISOString().split('T')[0]);
  };

  return (
    <div className="date-range-filter">
      <div className="date-range-presets">
        {presets.map(preset => (
          <button
            key={preset.days}
            className="date-preset-btn"
            onClick={() => setPreset(preset.days)}
          >
            {preset.label}
          </button>
        ))}
      </div>
      {/* BOTH date inputs are ours. The two bare <label> elements they sat beside named
          nothing - a <label> with no `htmlFor` and no control inside it is not a name source
          for anything - so DateField takes the words as its own `label` and the pair finally
          has an accessible name. ISO in, ISO out: `onStartChange`/`onEndChange` still receive
          exactly the 'YYYY-MM-DD' string `e.target.value` gave them, which is why `setPreset`
          above needs no change. */}
      <DateField label="From:" value={startDate} onChange={onStartChange} />
      <DateField label="To:" value={endDate} onChange={onEndChange} />
    </div>
  );
};

export default { BarChart, DonutChart, Sparkline, ProgressBar, StatsMini, DateRangePicker };

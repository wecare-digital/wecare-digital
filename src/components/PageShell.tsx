/**
 * PageShell Component - WECARE.DIGITAL
 * Wraps inner pages with section header + scrollable tab bar.
 * Sits between Layout's breadcrumbs and page content.
 * Does NOT break existing pages — just wraps them.
 */

import React, { useState } from 'react';

export interface ShellTab {
  id: string;
  label: string;
  icon?: string;
  divider?: boolean; // Show a visual separator before this tab
}

interface PageShellProps {
  title: string;
  subtitle?: string;
  tabs: ShellTab[];
  defaultTab?: string;
  activeTab?: string;
  actions?: React.ReactNode;
  /** Optional page-owned navigation below the heading; existing tab bars are unchanged. */
  navigation?: React.ReactNode;
  children: (activeTab: string) => React.ReactNode;
  className?: string;
  onTabChange?: (tabId: string) => void;
  /** Hide the title/tab chrome when this shell is embedded inside a canonical workspace shell. */
  showChrome?: boolean;
}

const PageShell: React.FC<PageShellProps> = ({
  title,
  subtitle,
  tabs,
  defaultTab,
  activeTab: controlledTab,
  actions,
  navigation,
  children,
  className = '',
  onTabChange,
  showChrome = true,
}) => {
  const [internalTab, setActiveTab] = useState(defaultTab || tabs[0]?.id || '');
  const activeTab = controlledTab ?? internalTab;

  const handleTabClick = (tabId: string) => {
    setActiveTab(tabId);
    onTabChange?.(tabId);
  };

  return (
    <div className={`page-shell ${className}`}>
      { showChrome && (
        <>
          <div className="ps-header">
            <div className="ps-header-left">
              <span className="ps-eyebrow">Workspace</span>
              <h1 className="ps-title">{title}</h1>
              {subtitle && <p className="ps-subtitle">{subtitle}</p>}
            </div>
            {actions && <div className="ps-header-actions">{actions}</div>}
          </div>

          {navigation && <div className="ps-navigation">{navigation}</div>}

          {tabs.length > 0 && <div className="ps-tabs-wrapper">
            <div className="ps-tabs" role="tablist">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === tab.id}
                  className={`ps-tab ${activeTab === tab.id ? 'active' : ''}${tab.divider ? ' ps-tab-after-divider' : ''}`}
                  onClick={() => handleTabClick(tab.id)}
                >
                  {tab.icon && <span className="ps-tab-icon" aria-hidden="true" title={tab.label}>{tab.icon}</span>}
                  {!tab.icon && tab.label}
                </button>
              ))}
            </div>
          </div>}

          {(tabs.length > 0 || navigation) && <div className="ps-separator" />}
        </>
      ) }

      {/* Tab Content */}
      <div className="ps-content" role="tabpanel">
        {children(activeTab)}
      </div>
    </div>
  );
};

export default PageShell;

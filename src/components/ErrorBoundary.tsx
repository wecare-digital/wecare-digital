/**
 * Error Boundary Component
 * Catches JavaScript errors in child components and displays fallback UI
 * Shows error code in production for support reference
 */

import React, { Component, ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  /** Rendered instead of the error card. `null` hides the failed part and keeps the page. */
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
  errorCode: string;
}

class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null, errorCode: '' };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    const errorCode = `ERR-${Date.now().toString(36).toUpperCase()}`;
    return { hasError: true, error, errorCode };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
    this.setState({ errorInfo });
  }

  handleReload = () => { window.location.reload(); };

  /**
   * HOME, NOT THE STAFF DASHBOARD. Corrected 2026-10-01.
   *
   * This target used to be the staff dashboard route inside the authenticated workspace
   * tree, with the button below labelled "Dashboard". The old path is deliberately NOT
   * spelled out here: a small component mounted on every public page has no legitimate use
   * for the token - not in a target, and not in a comment that a later edit could copy back
   * into one.
   *
   * It was wrong because of where this component is mounted: `src/pages/_app.tsx` renders
   * `<ErrorBoundary>` inside its `if ( isPublic )` branch, so a CUSTOMER who hits a render
   * error on any public page — cart, checkout, shop, a blog post — was offered a button
   * into the internal Cognito staff login. The escape hatch from a broken public page took
   * them somewhere they cannot sign in to and did not ask for.
   *
   * A full document load rather than a router navigation, deliberately: the React tree has
   * already failed by the time this renders, so the router's own state is the least
   * trustworthy thing available. `src/pages/404.tsx` records the same reasoning for its
   * anchor. The target is a literal `/`, so no path, query or fragment is forwarded.
   */
  handleGoHome = () => { window.location.href = '/'; };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback !== undefined) return this.props.fallback;

      return (
        <div style={styles.container}>
          <div style={styles.card}>
            <div style={styles.icon}>
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#1a3a2a" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
            </div>
            <h2 style={styles.title}>Something went wrong</h2>
            <p style={styles.message}>
              An unexpected error occurred. Please try refreshing the page.
            </p>
            <p style={styles.errorCode}>
              Reference: {this.state.errorCode}
            </p>
            {process.env.NODE_ENV === 'development' && this.state.error && (
              <details style={styles.details}>
                <summary style={styles.summary}>Error Details</summary>
                <pre style={styles.errorText}>
                  {this.state.error.toString()}
                  {this.state.errorInfo?.componentStack}
                </pre>
              </details>
            )}
            <div style={styles.buttons}>
              <button style={styles.primaryBtn} onClick={this.handleReload}>Refresh</button>
              <button style={styles.secondaryBtn} onClick={this.handleGoHome}>Home</button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const styles: Record<string, React.CSSProperties> = {
  container: { display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', backgroundColor: '#f5f5f5', padding: '20px' },
  card: { backgroundColor: '#fff', borderRadius: '16px', padding: '40px', maxWidth: '500px', width: '100%', textAlign: 'center', boxShadow: '0 4px 20px rgba(0,0,0,0.1)' },
  icon: { marginBottom: '16px' },
  title: { fontSize: '24px', fontWeight: 600, color: '#1a1a1a', margin: '0 0 12px 0' },
  message: { fontSize: '14px', color: '#666', margin: '0 0 8px 0', lineHeight: 1.5 },
  errorCode: { fontSize: '12px', color: '#9ca3af', margin: '0 0 24px 0', fontFamily: 'monospace' },
  details: { textAlign: 'left', marginBottom: '24px', backgroundColor: '#f9f9f9', borderRadius: '8px', padding: '12px' },
  summary: { cursor: 'pointer', fontWeight: 500, color: '#333' },
  errorText: { fontSize: '12px', color: '#c00', overflow: 'auto', maxHeight: '200px', marginTop: '12px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' },
  buttons: { display: 'flex', gap: '12px', justifyContent: 'center', flexWrap: 'wrap' },
  primaryBtn: { padding: '12px 24px', backgroundColor: '#1a1a1a', color: '#fff', border: 'none', borderRadius: '13px', cursor: 'pointer', fontSize: '14px', fontWeight: 500, minHeight: '44px' },
  secondaryBtn: { padding: '12px 24px', backgroundColor: '#fff', color: '#1a1a1a', border: '1.5px solid #1a1a1a', borderRadius: '13px', cursor: 'pointer', fontSize: '14px', fontWeight: 500, minHeight: '44px' },
};

export default ErrorBoundary;

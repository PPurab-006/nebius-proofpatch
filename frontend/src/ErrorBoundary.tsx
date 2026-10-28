import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
    errorInfo: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error caught by ErrorBoundary:', error, errorInfo);
    this.setState({ error, errorInfo });
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            minHeight: '100vh',
            backgroundColor: '#050505',
            color: '#F4F5F0',
            padding: '2rem',
            fontFamily: 'monospace',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '1rem',
          }}
        >
          <div
            style={{
              maxWidth: '650px',
              width: '100%',
              backgroundColor: '#0B0D0A',
              border: '1px solid #FF5C68',
              borderRadius: '8px',
              padding: '1.5rem',
              boxShadow: '0 0 20px rgba(255, 92, 104, 0.2)',
            }}
          >
            <h2 style={{ color: '#FF5C68', margin: '0 0 0.5rem 0', fontSize: '1rem' }}>
              Patchworks Interface Error
            </h2>
            <p style={{ color: '#969B90', fontSize: '0.8rem', margin: '0 0 1rem 0' }}>
              {this.state.error?.message || 'An unexpected error occurred in the workbench interface.'}
            </p>
            {this.state.error?.stack && (
              <pre
                style={{
                  backgroundColor: '#050505',
                  border: '1px solid #242820',
                  padding: '0.75rem',
                  borderRadius: '4px',
                  fontSize: '0.7rem',
                  color: '#969B90',
                  maxHeight: '180px',
                  overflow: 'auto',
                  whiteSpace: 'pre-wrap',
                }}
              >
                {this.state.error.stack}
              </pre>
            )}
            <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem' }}>
              <button
                onClick={() => {
                  window.location.href = window.location.origin;
                }}
                style={{
                  backgroundColor: '#B7FF3C',
                  color: '#050505',
                  border: 'none',
                  padding: '0.5rem 1rem',
                  borderRadius: '4px',
                  fontWeight: 'bold',
                  fontSize: '0.75rem',
                  cursor: 'pointer',
                }}
              >
                Reset & Reload Workbench
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

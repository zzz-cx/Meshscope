class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('Error caught by boundary:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{padding: '20px', color: 'red'}}>
          <h2>出错了</h2>
          <pre>{this.state.error.toString()}</pre>
        </div>
      );
    }
    return this.props.children;
  }
}

const App = () => {
  return (
    <ErrorBoundary>
      <React.StrictMode>
        <div style={{color: 'black'}}>
          <TopologyGraph />
        </div>
      </React.StrictMode>
    </ErrorBoundary>
  );
};

const renderApp = () => {
  console.log("Starting app render");
  const root = document.getElementById('root');
  if (root && window.TopologyGraph) {
    ReactDOM.render(<App />, root);
    console.log("App rendered");
  } else {
    console.error("Root element or TopologyGraph not found");
  }
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', renderApp);
} else {
  renderApp();
} 
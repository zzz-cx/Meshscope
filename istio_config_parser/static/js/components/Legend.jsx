window.Legend = () => (
  <div className="legend">
    <div className="legend-item">
      <svg width="20" height="20">
        <circle cx="10" cy="10" r="8" className="legend-service"/>
      </svg>
      <span>服务</span>
    </div>
    <div className="legend-item">
      <svg width="20" height="20">
        <path d="M10,2 L18,10 L10,18 L2,10 Z" className="legend-virtualservice"/>
      </svg>
      <span>Gateway</span>
    </div>
    <div className="legend-item">
      <svg width="20" height="20">
        <rect x="2" y="2" width="16" height="16" className="legend-subset"/>
      </svg>
      <span>服务版本</span>
    </div>
    <div className="legend-item">
      <svg width="20" height="20">
        <polygon points="10,2 14,6 14,14 10,18 6,14 6,6" className="legend-circuit-breaker"/>
      </svg>
      <span>熔断配置</span>
    </div>
  </div>
); 
// import ConfigGraph from './ConfigGraph.jsx';

window.ServiceDetails = ({ service, details }) => {
  // 添加组件检查
  React.useEffect(() => {
    if (!window.DataPlaneGraph) {
      console.error("DataPlaneGraph component is not loaded");
    }
  }, []);

  if (!service || !details) {
    return (
      <div className="service-details">
        <p>选择一个服务查看详情</p>
      </div>
    );
  }

  const configs = details.configurations || {};
  const relations = details.relations || {};
  const dataPlane = details.dataPlane || {};

  console.log('Details:', details);
  console.log('Relations:', relations);
  console.log('CircuitBreaker:', configs.circuitBreaker);

  return (
    <div className="service-details">
      <h3>{service} 配置详情</h3>
      {details.relations.rateLimit && (
        <RateLimitInfo rateLimit={details.relations.rateLimit} />
      )}

      <div className="control-plane-section">
        <h4>控制平面配置</h4>
        <ConfigGraph serviceDetails={details} />

        {configs.circuitBreaker && (
          <CircuitBreakerInfo circuitBreaker={configs.circuitBreaker} />
        )}

        {window.ConfigMindMap && configs.virtualServices && configs.virtualServices.length > 0 && (
          <ConfigMindMap config={configs.virtualServices[0]} />
        )}
        {window.ConfigMindMap && configs.destinationRules && configs.destinationRules.length > 0 && (
          <ConfigMindMap config={configs.destinationRules[0]} />
        )}
      </div>

      <div className="config-details">
        {configs.virtualServices && configs.virtualServices.length > 0 && (
          <ConfigSection
            title="VirtualService 配置"
            items={configs.virtualServices}
          />
        )}
        {configs.destinationRules && configs.destinationRules.length > 0 && (
          <ConfigSection
            title="DestinationRule 配置"
            items={configs.destinationRules}
          />
        )}
        {relations.subsets && relations.subsets.length > 0 && (
          <VersionList versions={relations.subsets} />
        )}
      </div>
    </div>
  );
};

const ConfigSection = ({ title, items }) => (
  <div className="config-section">
    <h4>{title}</h4>
    {items.map((item, index) => (
      <div key={index} className="config-item">
        <pre>{JSON.stringify(item, null, 2)}</pre>
      </div>
    ))}
  </div>
);

const VersionList = ({ versions }) => (
  <div className="config-section">
    <h4>服务版本</h4>
    <ul className="version-list">
      {versions.map((version, index) => (
        <li key={index} className="version-item">
          <span className="version-badge">v{version.version}</span>
          {version.name}
        </li>
      ))}
    </ul>
  </div>
);

const RateLimitInfo = ({ rateLimit }) => {
  if (!rateLimit || !Array.isArray(rateLimit) || rateLimit.length === 0) {
    return (
      <div className="info-section">
        <h4>限流规则</h4>
        <p>暂无限流规则</p>
      </div>
    );
  }

  return (
    <div className="config-section">
      <h4>限流配置</h4>
      {rateLimit.map((rule, index) => (
        <div key={index} className="rate-limit-info">
          <div className="rate-limit-basic">
            <span className="rate-limit-value">
              {rule.requests_per_unit} 请求/{rule.unit}
            </span>
          </div>
          {rule.conditions && rule.conditions.map((condition, condIndex) => (
            <div key={condIndex} className="rate-limit-condition">
              <span className="condition-label">请求条件:</span>
              <span className="condition-value">
                {condition.name}: {condition.value}
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
};

// 熔断规则组件
const CircuitBreakerInfo = ({ circuitBreaker }) => {
  if (!circuitBreaker) return null;
  
  // 检查是否有非空配置
  const hasGlobalConfig = circuitBreaker.global_ !== null;
  const hasSubsetConfig = circuitBreaker.subsets && 
                         Object.keys(circuitBreaker.subsets).length > 0 && 
                         Object.values(circuitBreaker.subsets).some(config => config !== null);
  
  // 如果没有任何配置，不显示组件
  if (!hasGlobalConfig && !hasSubsetConfig) return null;
  
  const renderConnectionPool = (cp) => {
    if (!cp) return <p>未配置连接池</p>;
    
    return (
      <div className="circuit-breaker-section">
        <h5>连接池配置</h5>
        <div className="cb-details">
          {cp.http && (
            <div className="cb-http">
              <h6>HTTP设置</h6>
              <ul className="cb-list">
                {cp.http.http1MaxPendingRequests !== undefined && (
                  <li>HTTP1最大等待请求数: <span className="cb-value">{cp.http.http1MaxPendingRequests}</span></li>
                )}
                {cp.http.http2MaxRequests !== undefined && (
                  <li>HTTP2最大请求数: <span className="cb-value">{cp.http.http2MaxRequests}</span></li>
                )}
                {cp.http.maxRequestsPerConnection !== undefined && (
                  <li>每连接最大请求数: <span className="cb-value">{cp.http.maxRequestsPerConnection}</span></li>
                )}
                {cp.http.maxRetries !== undefined && (
                  <li>最大重试次数: <span className="cb-value">{cp.http.maxRetries}</span></li>
                )}
              </ul>
            </div>
          )}
          
          {cp.tcp && (
            <div className="cb-tcp">
              <h6>TCP设置</h6>
              <ul className="cb-list">
                {cp.tcp.maxConnections !== undefined && (
                  <li>最大连接数: <span className="cb-value">{cp.tcp.maxConnections}</span></li>
                )}
                {cp.tcp.connectTimeout !== undefined && (
                  <li>连接超时: <span className="cb-value">{cp.tcp.connectTimeout}</span></li>
                )}
              </ul>
            </div>
          )}
        </div>
      </div>
    );
  };
  
  const renderOutlierDetection = (od) => {
    if (!od) return <p>未配置异常检测</p>;
    
    return (
      <div className="circuit-breaker-section">
        <h5>异常检测</h5>
        <ul className="cb-list">
          {od.baseEjectionTime !== undefined && (
            <li>基础驱逐时间: <span className="cb-value">{od.baseEjectionTime}</span></li>
          )}
          {od.consecutive5xxErrors !== undefined && (
            <li>连续5xx错误数: <span className="cb-value">{od.consecutive5xxErrors}</span></li>
          )}
          {od.interval !== undefined && (
            <li>检测间隔: <span className="cb-value">{od.interval}</span></li>
          )}
          {od.maxEjectionPercent !== undefined && (
            <li>最大驱逐百分比: <span className="cb-value">{od.maxEjectionPercent}%</span></li>
          )}
          {od.minHealthPercent !== undefined && (
            <li>最小健康百分比: <span className="cb-value">{od.minHealthPercent}%</span></li>
          )}
        </ul>
      </div>
    );
  };
  
  return (
    <div className="config-section circuit-breaker-info">
      <h4>熔断配置</h4>
      
      {/* 全局熔断配置 */}
      {circuitBreaker.global_ && (
        <div className="cb-global">
          <h5>全局熔断配置</h5>
          {renderConnectionPool(circuitBreaker.global_.connectionPool)}
          {renderOutlierDetection(circuitBreaker.global_.outlierDetection)}
        </div>
      )}
      
      {/* 子集熔断配置 */}
      {circuitBreaker.subsets && Object.keys(circuitBreaker.subsets).length > 0 && (
        <div className="cb-subsets">
          <h5>子集熔断配置</h5>
          {Object.entries(circuitBreaker.subsets).map(([subsetName, config], index) => {
            // 跳过null配置
            if (config === null) return null;
            
            return (
              <div key={index} className="cb-subset">
                <h6 className="subset-name">子集: {subsetName}</h6>
                {renderConnectionPool(config.connectionPool)}
                {renderOutlierDetection(config.outlierDetection)}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

// export default ServiceDetails; 
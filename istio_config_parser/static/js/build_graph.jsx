const TopologyGraph = () => {
  const [data, setData] = React.useState({
    services: [],
    serviceRelations: {},
    configurations: {}
  });
  const [selectedService, setSelectedService] = React.useState(null);
  const [serviceDetails, setServiceDetails] = React.useState(null);

  const renderMainGraph = (svg) => {
    svg.selectAll("*").remove();
    const width = svg.node().getBoundingClientRect().width;
    const height = svg.node().getBoundingClientRect().height;

    // 创建节点数组
    const nodes = [];
    const nodeSet = new Set();
    
    // 添加服务节点
    data.services.forEach(service => {
      nodes.push({
        name: service.name,
        type: 'service',
        namespace: service.namespace,
        fixed: true,  // 固定位置
        serviceObj: service
      });
      nodeSet.add(service.name);
    });

    // 创建连接关系
    const links = [];
    const gateways = new Set();

    // 1. 收集所有网关节点
    Object.entries(data.serviceRelations).forEach(([serviceName, relations]) => {
      if (relations.gateways && relations.gateways.length > 0) {
        relations.gateways.forEach(gateway => {
          const gatewayId = gateway.name;
          if (!nodeSet.has(gatewayId)) {
            nodes.push({
              name: gatewayId,
              type: 'gateway',
              namespace: gateway.namespace,
              fixed: true  // 固定位置
            });
            nodeSet.add(gatewayId);
            gateways.add(gatewayId);
          }
          
          // 添加网关到服务的连接
          links.push({
            source: gatewayId,
            target: serviceName,
            type: 'gateway'
          });
        });
      }
    });

    // 2. 添加服务子集节点
    Object.entries(data.serviceRelations).forEach(([serviceName, relations]) => {
      // 添加子集关系
      if (relations.subsets && relations.subsets.length > 0) {
        relations.subsets.forEach(subset => {
          const subsetNodeId = `${serviceName}-${subset.name}`;
          if (!nodeSet.has(subsetNodeId)) {
            nodes.push({
              name: subsetNodeId,
              displayName: subset.name,
              type: 'subset',
              version: subset.version || subset.name,
              parentService: serviceName,
              fixed: true  // 固定位置
            });
            nodeSet.add(subsetNodeId);
          }
          links.push({
            source: serviceName,
            target: subsetNodeId,
            type: 'subset'
          });
        });
      }
    });
    
    // 3. 添加服务间的直接连接关系 (通过数据平面)
    Object.entries(data.serviceRelations).forEach(([serviceName, relations]) => {
      if (relations.dataPlane && relations.dataPlane.outbound) {
        relations.dataPlane.outbound.forEach(outbound => {
          const targetService = outbound.service;
          if (nodeSet.has(targetService) && serviceName !== targetService) {
            links.push({
              source: serviceName,
              target: targetService,
              type: 'dataplane',
              port: outbound.port
            });
          }
        });
      }
    });

    console.log("Nodes:", nodes);
    console.log("Links:", links);

    // 计算服务节点的初始布局
    const serviceRadius = Math.min(width, height) * 0.35;
    const serviceCount = nodes.filter(n => n.type === 'service').length;
    const angleStep = (2 * Math.PI) / serviceCount;
    
    let serviceIndex = 0;
    nodes.forEach(node => {
      if (node.type === 'service') {
        const angle = serviceIndex * angleStep;
        node.fx = width/2 + serviceRadius * Math.cos(angle);
        node.fy = height/2 + serviceRadius * Math.sin(angle);
        serviceIndex++;
      }
    });
    
    // 为子集和网关节点设置位置
    nodes.forEach(node => {
      if (node.type === 'subset') {
        // 找到父服务节点
        const parentNode = nodes.find(n => n.name === node.parentService);
        if (parentNode) {
          // 将子集节点放在父服务旁边
          const childrenCount = nodes.filter(n => n.type === 'subset' && n.parentService === node.parentService).length;
          const childIndex = nodes.filter(n => n.type === 'subset' && n.parentService === node.parentService).findIndex(n => n.name === node.name);
          const offsetAngle = (childIndex - (childrenCount-1)/2) * (Math.PI/6);
          const distance = 80;
          
          node.fx = parentNode.fx + distance * Math.cos(offsetAngle);
          node.fy = parentNode.fy + distance * Math.sin(offsetAngle);
        }
      } else if (node.type === 'gateway') {
        // 找到连接的服务节点
        const connectedServices = links
          .filter(link => link.source === node.name || link.target === node.name)
          .map(link => link.source === node.name ? link.target : link.source);
        
        if (connectedServices.length > 0) {
          // 计算所有连接服务的平均位置
          const connectedNodes = nodes.filter(n => connectedServices.includes(n.name));
          const avgX = connectedNodes.reduce((sum, n) => sum + n.fx, 0) / connectedNodes.length;
          const avgY = connectedNodes.reduce((sum, n) => sum + n.fy, 0) / connectedNodes.length;
          
          // 将网关放在连接服务的一侧
          const offsetX = avgX - width/2;
          const offsetY = avgY - height/2;
          const angle = Math.atan2(offsetY, offsetX);
          const distance = 120;
          
          node.fx = avgX - distance * Math.cos(angle);
          node.fy = avgY - distance * Math.sin(angle);
        } else {
          // 没有连接的服务，放在中心点附近
          node.fx = width/2 + 100;
          node.fy = height/2 + 100;
        }
      }
    });

    const simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links).id(d => d.name).distance(150))
      .force('charge', d3.forceManyBody().strength(-300))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .alpha(0.3) // 降低模拟强度，让固定位置的节点更加稳定
      .alphaDecay(0.02);

    // 箭头定义
    svg.append("defs").selectAll("marker")
      .data(["gateway", "subset", "dataplane"])
      .enter().append("marker")
      .attr("id", d => `arrow-${d}`)
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 15)
      .attr("refY", 0)
      .attr("markerWidth", 8)
      .attr("markerHeight", 8)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-5L10,0L0,5")
      .attr("fill", d => d === "subset" ? "#2ca02c" : d === "gateway" ? "#ff7f0e" : "#999");

    // 绘制连接线
    const link = svg.append("g")
      .selectAll("line")
      .data(links)
      .enter().append("line")
      .attr("stroke", d => {
        if (d.type === 'subset') return "#2ca02c";
        if (d.type === 'gateway') return "#ff7f0e";
        return "#999";
      })
      .attr("stroke-width", d => d.type === 'dataplane' ? 1 : 2)
      .attr("stroke-dasharray", d => {
        if (d.type === 'subset') return "5,5";
        if (d.type === 'dataplane') return "2,2";
        return ""; 
      })
      .attr("marker-end", d => `url(#arrow-${d.type})`)
      .attr("class", d => `link-${d.type}`);

    // 创建节点组
    const node = svg.append("g")
      .selectAll("g")
      .data(nodes)
      .enter().append("g")
      .attr("class", d => `node-${d.type}`)
      .call(d3.drag()
        .on("start", dragstarted)
        .on("drag", dragged)
        .on("end", dragended))
      .on("click", (event, d) => {
        if (d.type === 'service') {
          setSelectedService(d.name);
        } else if (d.type === 'subset') {
          setSelectedService(d.parentService);
        }
      });

    // 根据节点类型使用不同的形状和颜色
    node.each(function(d) {
      const g = d3.select(this);
      if (d.type === 'service') {
        g.append("circle")
          .attr("r", 18)
          .attr("fill", "#69b3a2")
          .attr("stroke", "#fff")
          .attr("stroke-width", 2);
      } else if (d.type === 'gateway') {
        g.append("polygon")
          .attr("points", "0,-15 13,7 -13,7")
          .attr("fill", "#ff7f0e")
          .attr("stroke", "#fff")
          .attr("stroke-width", 2);
      } else if (d.type === 'subset') {
        g.append("rect")
          .attr("x", -12)
          .attr("y", -12)
          .attr("width", 24)
          .attr("height", 24)
          .attr("fill", "#2ca02c")
          .attr("stroke", "#fff")
          .attr("stroke-width", 2);
      }
    });

    // 添加标签
    node.append("text")
      .attr("dx", d => d.type === 'subset' ? 0 : 22)
      .attr("dy", d => d.type === 'subset' ? 30 : ".35em")
      .attr("text-anchor", d => d.type === 'subset' ? "middle" : "start")
      .attr("fill", "#333")
      .attr("font-weight", "bold")
      .text(d => {
        if (d.type === 'subset') {
          return d.displayName || d.version;
        }
        return d.name;
      });

    // 添加悬停提示
    node.append("title")
      .text(d => {
        if (d.type === 'service') {
          return `服务: ${d.name}\n命名空间: ${d.namespace}`;
        } else if (d.type === 'gateway') {
          return `网关: ${d.name}\n命名空间: ${d.namespace}`;
        } else if (d.type === 'subset') {
          return `版本: ${d.version}\n服务: ${d.parentService}`;
        }
        return d.name;
      });

    // 高亮连接线功能
    node.on("mouseover", function(event, d) {
      d3.select(this).style("cursor", "pointer");
      
      // 隐藏其他节点连接线, 突出显示当前节点的连接线
      link.attr("opacity", link => {
        return (link.source.name === d.name || link.target.name === d.name) ? 1 : 0.1;
      });
    })
    .on("mouseout", function() {
      link.attr("opacity", 1);
    });

    function ticked() {
      link
        .attr("x1", d => d.source.x)
        .attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x)
        .attr("y2", d => d.target.y);

      node
        .attr("transform", d => `translate(${d.x},${d.y})`);
    }

    function dragstarted(event, d) {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      d.fx = d.x;
      d.fy = d.y;
    }

    function dragged(event, d) {
      d.fx = event.x;
      d.fy = event.y;
    }

    function dragended(event, d) {
      if (!event.active) simulation.alphaTarget(0);
      // 不释放位置，保持拖动后的位置固定
      // d.fx = null;
      // d.fy = null;
    }

    simulation.on("tick", ticked);
  };

  // 渲染服务详情
  const renderServiceDetails = () => {
    if (!selectedService || !serviceDetails) return null;

    const details = serviceDetails.configurations;
    const relations = serviceDetails.relations;
    const dataPlane = serviceDetails.dataPlane;

    return (
      <div className="service-details">
        <h3>基本信息</h3>
        <div className="config-section">
          <p><strong>服务名称:</strong> {selectedService}</p>
          {relations.gateways && relations.gateways.length > 0 && (
            <div>
              <h4>网关</h4>
              <ul>
                {relations.gateways.map((gateway, idx) => (
                  <li key={idx}>
                    <strong>{gateway.name}</strong> (命名空间: {gateway.namespace})
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        
        {relations.subsets && relations.subsets.length > 0 && (
          <div className="config-section">
            <h4>服务版本</h4>
            <ul>
              {relations.subsets.map((subset, idx) => (
                <li key={idx}>
                  <strong>{subset.name}</strong> (版本: {subset.version})
                  <br/>
                  标签: {JSON.stringify(subset.labels)}
                  {details.weights && details.weights[subset.name] && (
                    <div>
                      权重: <strong>{details.weights[subset.name].weight}</strong>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
        
        {details.virtualServices && details.virtualServices.length > 0 && (
          <div className="config-section">
            <h4>虚拟服务配置</h4>
            {details.virtualServices.map((vs, idx) => (
              <div key={idx} className="config-item">
                <h5>{vs.name}</h5>
                <p>命名空间: {vs.namespace}</p>
                <p>路由规则数: {vs.rules ? vs.rules.length : 0}</p>
                {vs.rules && vs.rules.map((rule, ruleIdx) => (
                  <div key={ruleIdx} className="rule-item">
                    <pre>{JSON.stringify(rule, null, 2)}</pre>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
        
        {details.circuitBreaker && details.circuitBreaker.global && (
          <div className="config-section">
            <h4>熔断配置</h4>
            <pre>{JSON.stringify(details.circuitBreaker, null, 2)}</pre>
          </div>
        )}
        
        {dataPlane.outbound && dataPlane.outbound.length > 0 && (
          <div className="config-section">
            <h4>出站连接</h4>
            <ul>
              {dataPlane.outbound.map((outbound, idx) => (
                <li key={idx}>
                  <strong>{outbound.service}</strong> (端口: {outbound.port})
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    );
  };

  // 获取数据
  React.useEffect(() => {
    fetch('/api/services')
      .then(response => response.json())
      .then(data => {
        console.log("Received data:", data);
        setData(data);
      })
      .catch(error => console.error("Error fetching data:", error));
  }, []);

  // 获取服务详情
  React.useEffect(() => {
    if (selectedService) {
      fetch(`/api/services/${selectedService}/details`)
        .then(response => response.json())
        .then(details => {
          console.log("Service details:", details);
          setServiceDetails(details);
        })
        .catch(error => console.error("Error fetching service details:", error));
    }
  }, [selectedService]);

  // 渲染主图
  React.useEffect(() => {
    if (data.services.length > 0) {
      const mainSvg = d3.select('#main-graph');
      renderMainGraph(mainSvg);
    }
  }, [data]);

  return (
    <div className="container">
      <div className="main-graph">
        <h2>服务拓扑图</h2>
        <p>状态: {data.services.length} 个服务</p>
        <div className="legend">
          <div className="legend-item">
            <svg width="20" height="20">
              <circle cx="10" cy="10" r="8" fill="#69b3a2"/>
            </svg>
            <span>服务</span>
          </div>
          <div className="legend-item">
            <svg width="20" height="20">
              <polygon points="10,2 16,16 4,16" fill="#ff7f0e"/>
            </svg>
            <span>网关</span>
          </div>
          <div className="legend-item">
            <svg width="20" height="20">
              <rect x="4" y="4" width="12" height="12" fill="#2ca02c"/>
            </svg>
            <span>服务版本</span>
          </div>
          <div className="legend-item">
            <svg width="30" height="20">
              <line x1="5" y1="10" x2="25" y2="10" stroke="#2ca02c" stroke-width="2" stroke-dasharray="5,5"/>
            </svg>
            <span>版本关系</span>
          </div>
          <div className="legend-item">
            <svg width="30" height="20">
              <line x1="5" y1="10" x2="25" y2="10" stroke="#999" stroke-width="1" stroke-dasharray="2,2"/>
            </svg>
            <span>服务调用</span>
          </div>
        </div>
        <svg id="main-graph" width="800" height="600"></svg>
      </div>
      <div className={`detail-graph ${!selectedService ? 'hidden' : ''}`}>
        <h2>{selectedService ? `${selectedService} 服务详情` : ''}</h2>
        {renderServiceDetails()}
      </div>
      <style>{`
        .link-subset {
          stroke-dasharray: 5,5;
        }
        .link-dataplane {
          stroke-dasharray: 2,2;
        }
        .node-service circle:hover {
          fill: #4a9787;
        }
        .node-subset rect:hover {
          fill: #1e7a1e;
        }
        .node-gateway polygon:hover {
          fill: #d26200;
        }
      `}</style>
    </div>
  );
};

ReactDOM.render(
  <TopologyGraph />,
  document.getElementById('root')
);
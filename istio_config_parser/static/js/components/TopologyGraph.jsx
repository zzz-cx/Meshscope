const TopologyGraph = () => {
  console.log("TopologyGraph component initialized");

  const [data, setData] = React.useState({
    services: [],
    serviceRelations: {},
    configurations: {}
  });
  const [selectedService, setSelectedService] = React.useState(null);
  const [serviceDetails, setServiceDetails] = React.useState(null);

  // 添加网关节点的样式
  const nodeColors = {
    service: '#68B2A0',
    virtualservice: '#2E4057',
    gateway: '#4B0082',  // 添加网关节点的颜色
    subset: '#2ca02c',    // 子集节点颜色
    'circuit-breaker': '#fa8c16'  // 熔断器节点颜色
  };

  const nodeShapes = {
    service: d3.symbolCircle,
    virtualservice: d3.symbolDiamond,
    gateway: d3.symbolTriangle,  // 添加网关节点的形状
    subset: d3.symbolSquare,      // 子集节点形状
    'circuit-breaker': d3.symbolWye  // 熔断器使用六角星形状
  };

  // 定义连接线的样式
  const linkStyles = {
    virtualservice: {
      stroke: "#666",
      strokeWidth: 2,
      opacity: 0.8
    },
    gateway: {
      stroke: "#4B0082",  // 使用与网关节点匹配的颜色
      strokeWidth: 2,
      opacity: 0.8
    },
    subset: {
      stroke: "#2ca02c",
      strokeWidth: 2,
      opacity: 0.8
    },
    'circuit-breaker': {
      stroke: "#fa8c16",
      strokeWidth: 2,
      opacity: 0.8,
      strokeDasharray: "5,5"
    }
  };

  // 添加 drag 函数定义
  const drag = (simulation) => {
    return d3.drag()
      .on("start", (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on("drag", (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on("end", (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        // 保持节点位置固定
        // d.fx = null;
        // d.fy = null;
      });
  };

  // 添加 createArrowMarker 函数定义
  const createArrowMarker = (svg) => {
    svg.append("defs").selectAll("marker")
      .data(["virtualservice", "gateway", "subset", "circuit-breaker"])
      .enter().append("marker")
      .attr("id", d => `arrow-${d}`)
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 20)
      .attr("refY", 0)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-5L10,0L0,5")
      .attr("fill", d => linkStyles[d] ? linkStyles[d].stroke : "#999");
  };

  const renderMainGraph = (svg) => {
    console.log("renderMainGraph called with svg:", svg);
    console.log("Current data:", data);

    svg.selectAll("*").remove();
    const width = svg.node().getBoundingClientRect().width;
    const height = svg.node().getBoundingClientRect().height;
    const padding = 50; // 添加内边距

    // 创建节点数组
    const nodes = [];
    const nodeSet = new Set();
    
    // 添加服务节点
    data.services.forEach(service => {
      nodes.push({
        name: service.name,
        type: 'service',
        namespace: service.namespace,
        fixed: true
      });
      nodeSet.add(service.name);
    });

    // 创建连接关系
    const links = [];
    const virtualServices = new Set();
    const gateways = new Set();

    // 网关节点的收集逻辑
    Object.entries(data.serviceRelations).forEach(([serviceName, relations]) => {
      if (relations.gateways && Array.isArray(relations.gateways) && relations.gateways.length > 0) {
        relations.gateways.forEach(gateway => {
          if (!nodeSet.has(gateway.name)) {
            nodes.push({
              name: gateway.name,
              type: 'gateway',
              namespace: gateway.namespace,
              fixed: true
            });
            nodeSet.add(gateway.name);
            gateways.add(gateway.name);
          }
          // 添加网关到服务的连接
          links.push({
            source: gateway.name,
            target: serviceName,
            type: 'gateway'
          });
        });
      }
    });

    // 添加虚拟服务节点
    Object.entries(data.serviceRelations).forEach(([serviceName, relations]) => {
      if (relations.incomingVirtualServices && relations.incomingVirtualServices.length > 0) {
        relations.incomingVirtualServices.forEach(vs => {
          if (typeof vs === 'string') {
            // 处理字符串情况
            if (!nodeSet.has(vs)) {
              nodes.push({
                name: vs,
                type: 'virtualservice',
                fixed: true
              });
              nodeSet.add(vs);
              virtualServices.add(vs);
            }
            links.push({
              source: vs,
              target: serviceName,
              type: 'virtualservice'
            });
          } else if (vs && typeof vs === 'object' && vs.name) {
            // 处理对象情况
            if (!nodeSet.has(vs.name)) {
              nodes.push({
                name: vs.name,
                type: 'virtualservice',
                namespace: vs.namespace,
                fixed: true
              });
              nodeSet.add(vs.name);
              virtualServices.add(vs.name);
            }
            links.push({
              source: vs.name,
              target: serviceName,
              type: 'virtualservice'
            });
          }
        });
      }
    });

    // 添加服务子集
    Object.entries(data.serviceRelations).forEach(([serviceName, relations]) => {
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
              fixed: true
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

    // 添加熔断器配置节点
    Object.entries(data.configurations || {}).forEach(([serviceName, configs]) => {
      if (configs.circuitBreaker && 
         (configs.circuitBreaker.global_ || 
         (configs.circuitBreaker.subsets && 
          Object.keys(configs.circuitBreaker.subsets).length > 0 &&
          // 检查子集中是否存在非null的配置
          Object.values(configs.circuitBreaker.subsets).some(config => config !== null)))) {
        
        console.log(`Found circuit breaker config for ${serviceName}:`, configs.circuitBreaker);
        
        // 创建熔断器节点
        const cbNodeId = `${serviceName}-cb`;
        if (!nodeSet.has(cbNodeId)) {
          nodes.push({
            name: cbNodeId,
            displayName: '熔断器',
            type: 'circuit-breaker',
            parentService: serviceName,
            fixed: true
          });
          nodeSet.add(cbNodeId);
          
          // 连接服务到熔断器
          links.push({
            source: serviceName,
            target: cbNodeId,
            type: 'circuit-breaker'
          });
          
          // 如果有子集特定的熔断配置，为它们创建连接
          if (configs.circuitBreaker.subsets) {
            Object.entries(configs.circuitBreaker.subsets).forEach(([subsetName, cbConfig]) => {
              // 忽略null配置
              if (cbConfig === null) return;
              
              const subsetNodeId = `${serviceName}-${subsetName}`;
              // 检查该子集节点是否存在
              if (nodeSet.has(subsetNodeId)) {
                links.push({
                  source: cbNodeId,
                  target: subsetNodeId,
                  type: 'circuit-breaker'
                });
              }
            });
          }
        }
      }
    });

    console.log("Processed nodes:", nodes);
    console.log("Processed links:", links);

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
          const distance = 60;
          
          node.fx = parentNode.fx + distance * Math.cos(offsetAngle);
          node.fy = parentNode.fy + distance * Math.sin(offsetAngle);
        }
      } else if (node.type === 'circuit-breaker') {
        // 熔断器节点放在服务节点附近
        const parentNode = nodes.find(n => n.name === node.parentService);
        if (parentNode) {
          // 放在服务节点的上方
          node.fx = parentNode.fx;
          node.fy = parentNode.fy - 70; // 上方一定距离
        }
      } else if (node.type === 'gateway') {
        // 找到连接的服务节点
        const connectedServices = links
          .filter(link => (link.source === node.name || link.target === node.name) && link.type === 'gateway')
          .map(link => link.source === node.name ? link.target : link.source);
        
        if (connectedServices.length > 0) {
          // 计算所有连接服务的平均位置
          const connectedNodes = nodes.filter(n => connectedServices.includes(n.name));
          const avgX = connectedNodes.reduce((sum, n) => sum + (n.fx || 0), 0) / connectedNodes.length;
          const avgY = connectedNodes.reduce((sum, n) => sum + (n.fy || 0), 0) / connectedNodes.length;
          
          // 将网关放在连接服务的一侧
          const offsetX = avgX - width/2;
          const offsetY = avgY - height/2;
          const angle = Math.atan2(offsetY, offsetX);
          const distance = 100;
          
          node.fx = avgX - distance * Math.cos(angle);
          node.fy = avgY - distance * Math.sin(angle);
        } else {
          // 没有连接的服务，放在中心点附近
          node.fx = width/2 + 100;
          node.fy = height/2 + 100;
        }
      } else if (node.type === 'virtualservice') {
        // 找到连接的服务节点
        const connectedServices = links
          .filter(link => (link.source === node.name || link.target === node.name) && link.type === 'virtualservice')
          .map(link => link.source === node.name ? link.target : link.source);
        
        if (connectedServices.length > 0) {
          const connectedNodes = nodes.filter(n => connectedServices.includes(n.name));
          const avgX = connectedNodes.reduce((sum, n) => sum + (n.fx || 0), 0) / connectedNodes.length;
          const avgY = connectedNodes.reduce((sum, n) => sum + (n.fy || 0), 0) / connectedNodes.length;
          
          // 将虚拟服务放在连接服务的一侧
          const offsetX = avgX - width/2;
          const offsetY = avgY - height/2;
          const angle = Math.atan2(offsetY, offsetX);
          const distance = 80;
          
          node.fx = avgX + distance * Math.cos(angle + Math.PI/4);
          node.fy = avgY + distance * Math.sin(angle + Math.PI/4);
        } else {
          node.fx = width/2 - 100;
          node.fy = height/2 - 100;
        }
      }
    });

    const simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links).id(d => d.name).distance(100))
      .force('charge', d3.forceManyBody().strength(-200))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(30))
      .alpha(0.3)
      .alphaDecay(0.02);

    createArrowMarker(svg);

    // 绘制连接线
    const link = svg.append("g")
      .selectAll("line")
      .data(links)
      .enter()
      .append("line")
      .attr("class", d => `link link-${d.type}`)
      .attr("stroke-width", d => {
        return (linkStyles[d.type] && linkStyles[d.type].strokeWidth) || 1;
      })
      .attr("stroke", d => {
        return (linkStyles[d.type] && linkStyles[d.type].stroke) || "#999";
      })
      .attr("opacity", d => {
        return (linkStyles[d.type] && linkStyles[d.type].opacity) || 1;
      })
      .attr("marker-end", d => `url(#arrow-${d.type})`);

    // 创建节点组
    const nodeGroup = svg.append("g")
      .selectAll(".node")
      .data(nodes)
      .enter()
      .append("g")
      .attr("class", d => `node node-${d.type}`)
      .attr("data-name", d => d.name)
      .call(drag(simulation))
      .on("click", (event, d) => {
        if (d.type === 'service') {
          event.stopPropagation();
          console.log("Node clicked:", d);
          setSelectedService(d.name);
        } else if (d.type === 'subset') {
          event.stopPropagation();
          console.log("Subset node clicked, parent service:", d.parentService);
          setSelectedService(d.parentService);
        } else if (d.type === 'circuit-breaker') {
          event.stopPropagation();
          console.log("Circuit breaker node clicked, parent service:", d.parentService);
          setSelectedService(d.parentService);
        }
      })
      .on("mouseover", function(event, d) {
        // 高亮与此节点相关的连接
        d3.select(this).style("cursor", "pointer");
        
        const relatedLinks = links.filter(link => 
          (link.source.name === d.name || link.source === d.name || 
          link.target.name === d.name || link.target === d.name)
        );
        
        // 淡化所有连接
        link.style("opacity", 0.1);
        
        // 高亮相关连接
        svg.selectAll("line")
          .filter(function() {
            const linkData = d3.select(this).datum();
            return relatedLinks.includes(linkData);
          })
          .style("opacity", 1)
          .style("stroke-width", d => {
            const baseWidth = (linkStyles[d.type] && linkStyles[d.type].strokeWidth) || 1;
            return baseWidth + 1;
          });
        
        // 高亮当前节点
        d3.select(this).select("path").style("stroke", "#ff6");
        d3.select(this).select("path").style("stroke-width", 3);
      })
      .on("mouseout", function() {
        // 恢复所有连接的正常样式
        link.style("opacity", d => {
          return (linkStyles[d.type] && linkStyles[d.type].opacity) || 1;
        })
        .style("stroke-width", d => {
          return (linkStyles[d.type] && linkStyles[d.type].strokeWidth) || 1;
        });
        
        // 恢复节点样式
        d3.select(this).select("path").style("stroke", "#fff");
        d3.select(this).select("path").style("stroke-width", 2);
      });

    // 添加节点形状
    nodeGroup.append("path")
      .attr("d", d => {
        const size = d.type === 'service' ? 400 : 200;
        const symbol = d3.symbol()
          .type(nodeShapes[d.type] || nodeShapes.service)
          .size(size);
        return symbol();
      })
      .attr("fill", d => nodeColors[d.type] || nodeColors.service)
      .attr("stroke", "#fff")
      .attr("stroke-width", 2);

    // 添加节点标签
    nodeGroup.append("text")
      .attr("dx", d => d.type === 'subset' ? 0 : 15)
      .attr("dy", d => d.type === 'subset' ? 25 : ".35em")
      .attr("text-anchor", d => d.type === 'subset' ? "middle" : "start")
      .style("fill", "#333")
      .style("font-weight", "bold")
      .style("font-size", "12px")
      .text(d => {
        if (d.type === 'subset') {
          return d.displayName || d.version;
        }
        return d.name;
      });

    // 添加悬停提示
    nodeGroup.append("title")
      .text(d => {
        if (d.type === 'service') {
          return `服务: ${d.name}\n命名空间: ${d.namespace || 'default'}`;
        } else if (d.type === 'gateway') {
          return `网关: ${d.name}\n命名空间: ${d.namespace || 'default'}`;
        } else if (d.type === 'subset') {
          return `版本: ${d.version}\n服务: ${d.parentService}`;
        } else if (d.type === 'virtualservice') {
          return `虚拟服务: ${d.name}\n命名空间: ${d.namespace || 'default'}`;
        }
        return d.name;
      });

    function ticked() {
      // 添加边界限制
      nodes.forEach(d => {
        if (!d.fx && !d.fy) {
          d.x = Math.max(padding, Math.min(width - padding, d.x || width/2));
          d.y = Math.max(padding, Math.min(height - padding, d.y || height/2));
        }
      });

      link
        .attr("x1", d => d.source.x || 0)
        .attr("y1", d => d.source.y || 0)
        .attr("x2", d => d.target.x || 0)
        .attr("y2", d => d.target.y || 0);

      nodeGroup
        .attr("transform", d => `translate(${d.x || 0},${d.y || 0})`);
    }

    simulation.on("tick", ticked);
    
    // 背景点击事件 - 取消选择服务
    svg.on("click", () => {
      setSelectedService(null);
    });
  };

  // 获取数据
  React.useEffect(() => {
    console.log("Fetching services data...");
    fetch('/api/services')
      .then(response => response.json())
      .then(data => {
        console.log("Received data:", data);
        if (data.services && Array.isArray(data.services)) {
          setData(data);
        } else {
          console.error("Invalid data format:", data);
        }
      })
      .catch(error => console.error("Error fetching data:", error));
  }, []);

  // 获取服务详情
  React.useEffect(() => {
    let mounted = true;

    if (selectedService) {
      console.log("Fetching details for service:", selectedService);
      fetch(`/api/services/${selectedService}/details`)
        .then(response => response.json())
        .then(details => {
          if (mounted) {
            console.log("Received service details:", details);
            setServiceDetails(details);
          }
        })
        .catch(error => {
          if (mounted) {
            console.error("Error fetching service details:", error);
            setServiceDetails(null);
          }
        });
    }

    return () => {
      mounted = false;
    };
  }, [selectedService]);

  // 渲染主图
  React.useEffect(() => {
    if (data.services && data.services.length > 0) {
      console.log("Rendering graph with data:", data);
      const svg = d3.select('#main-graph');
      
      // 确保 SVG 元素存在
      if (!svg.empty()) {
        renderMainGraph(svg);
      } else {
        console.error("SVG element not found");
      }
    }
  }, [data]);

  return (
    <div className="topology-container">
      <div className="main-graph">
        <h2 style={{color: 'black'}}>服务拓扑图</h2>
        <p style={{color: 'black'}}>状态: {data.services && data.services.length || 0} 个服务</p>
        <div className="legend">
          <div className="legend-item">
            <svg width="20" height="20">
              <circle cx="10" cy="10" r="8" fill={nodeColors.service}/>
            </svg>
            <span>服务</span>
          </div>
          <div className="legend-item">
            <svg width="20" height="20">
              <path d="M10,2 L18,10 L10,18 L2,10 Z" fill={nodeColors.virtualservice}/>
            </svg>
            <span>虚拟服务</span>
          </div>
          <div className="legend-item">
            <svg width="20" height="20">
              <path d="M10,2 L18,10 L2,10 Z" fill={nodeColors.gateway}/>
            </svg>
            <span>网关</span>
          </div>
          <div className="legend-item">
            <svg width="20" height="20">
              <rect x="4" y="4" width="12" height="12" fill={nodeColors.subset}/>
            </svg>
            <span>服务版本</span>
          </div>
          <div className="legend-item">
            <svg width="20" height="20">
              <path d="M10,0 L12,7 L20,7 L14,12 L16,20 L10,15 L4,20 L6,12 L0,7 L8,7 Z" 
                    transform="scale(0.7) translate(5,5)" 
                    fill={nodeColors['circuit-breaker']}/>
            </svg>
            <span>熔断配置</span>
          </div>
        </div>
        <svg 
          id="main-graph" 
          style={{
            width: '100%',
            height: 'calc(100vh - 150px)',
            minHeight: '500px',
            border: '1px solid #ccc',
            background: '#fff',
            borderRadius: '4px'
          }}
        ></svg>
      </div>
      {selectedService && (
        <div className="detail-panel">
          <div className="detail-header">
            <h3>{selectedService} 服务详情</h3>
            <button 
              onClick={() => setSelectedService(null)}
              className="close-button"
            >
              ×
            </button>
          </div>
          <window.ServiceDetails 
            service={selectedService} 
            details={serviceDetails} 
          />
          {serviceDetails && (
            <window.DataPlaneGraph 
              serviceDetails={serviceDetails} 
            />
          )}
        </div>
      )}
      <style>{`
        .node path {
          transition: all 0.2s;
        }
        .node path:hover {
          stroke: #ff6;
          stroke-width: 3px;
        }
        .node text {
          pointer-events: none;
        }
        .node-subset text {
          font-size: 10px;
        }
        .link {
          transition: opacity 0.2s;
        }
        .link-subset {
          stroke: ${linkStyles.subset.stroke};
        }
        .link-gateway {
          stroke: ${linkStyles.gateway.stroke};
        }
        .link-virtualservice {
          stroke: ${linkStyles.virtualservice.stroke};
        }
        .topology-container {
          display: flex;
          flex-direction: column;
          height: 100vh;
        }
        .main-graph {
          flex: 1;
          position: relative;
          overflow: hidden;
        }
        .detail-panel {
          position: fixed;
          right: 0;
          top: 0;
          width: 400px;
          height: 100vh;
          background: white;
          box-shadow: -2px 0 5px rgba(0,0,0,0.1);
          overflow: auto;
          z-index: 10;
          border-left: 1px solid #ddd;
          padding: 15px;
        }
        .detail-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          border-bottom: 1px solid #eee;
          padding-bottom: 10px;
          margin-bottom: 15px;
        }
        .close-button {
          background: none;
          border: none;
          font-size: 24px;
          cursor: pointer;
          color: #999;
        }
        .close-button:hover {
          color: #333;
        }
        .legend {
          display: flex;
          gap: 15px;
          padding: 8px;
          background: rgba(255,255,255,0.8);
          border-radius: 4px;
          margin-bottom: 10px;
        }
        .legend-item {
          display: flex;
          align-items: center;
          gap: 5px;
          font-size: 12px;
        }
      `}</style>
    </div>
  );
};

// 添加到全局对象中以便主应用使用
if (typeof window !== 'undefined') {
  window.TopologyGraph = TopologyGraph;
} 
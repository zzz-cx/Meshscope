const DataPlaneGraph = ({ serviceDetails }) => {
  const svgRef = React.useRef(null);
  
  React.useEffect(() => {
    if (!serviceDetails) return;
    
    const svg = d3.select(svgRef.current);
    renderDataPlaneGraph(svg, serviceDetails);
  }, [serviceDetails]);
  
  const renderDataPlaneGraph = (svg, details) => {
    console.log("Rendering data plane graph with details:", details);
    svg.selectAll("*").remove();
    const width = 500;
    const height = 300;
    
    const nodes = [];
    const links = [];
    
    // 添加主服务节点
    nodes.push({
      id: "service",
      label: "service",
      type: "service"
    });
    
    // 1. 处理子集信息 (Subsets)
    const subsets = [];
    if (details.relations && details.relations.subsets && details.relations.subsets.length > 0) {
      details.relations.subsets.forEach(subset => {
        subsets.push(subset.name);
        nodes.push({
          id: subset.name,
          label: `${subset.name}\n(${subset.version})`,
          type: "subset"
        });
      });
    }
    
    // 2. 处理权重信息 - 先检查VirtualService配置
    console.log("Configurations:", details.configurations);
    let weightInfo = {};
    
    // 直接从configurations.weights获取权重信息
    if (details.configurations && details.configurations.weights) {
      console.log("Found weights in configurations:", details.configurations.weights);
      Object.entries(details.configurations.weights).forEach(([subset, weightData]) => {
        if (weightData && weightData.weight !== undefined) {
          console.log(`Found control plane weight for ${subset}: ${weightData.weight}`);
          weightInfo[subset] = weightData.weight;
        }
      });
    }
    
    // 如果需要，也可以从VirtualService配置中获取权重
    if (details.configurations && details.configurations.virtualServices) {
      details.configurations.virtualServices.forEach(vs => {
        console.log("Processing VirtualService:", vs);
        if (vs.http) {
          vs.http.forEach(route => {
            if (route.route) {
              route.route.forEach(dest => {
                if (dest.destination && dest.destination.subset && dest.weight !== undefined) {
                  console.log(`Found weight for subset ${dest.destination.subset}: ${dest.weight}`);
                  weightInfo[dest.destination.subset] = dest.weight;
                }
              });
            }
          });
        }
      });
    }
    
    // 3. 处理数据平面权重信息
    console.log("DataPlane data:", details.dataPlane);
    if (details.dataPlane && details.dataPlane.weights) {
      Object.entries(details.dataPlane.weights).forEach(([subset, weightData]) => {
        if (weightData && weightData.weight !== undefined) {
          console.log(`Found data plane weight for subset ${subset}: ${weightData.weight}`);
          // 如果数据平面有权重信息，优先使用
          weightInfo[subset] = weightData.weight;
        }
      });
    }
    
    console.log("Final weight info:", weightInfo);
    
    // 创建子集到服务的连接
    subsets.forEach(subset => {
      const weight = weightInfo[subset] !== undefined ? weightInfo[subset] : 0;
      console.log(`Creating link for subset ${subset} with weight ${weight}`);
      links.push({
        source: subset,
        target: "service",
        type: "subset",
        weight: weight
      });
    });
    
    // 添加网关节点
    if (details.relations && details.relations.gateways && details.relations.gateways.length > 0) {
      details.relations.gateways.forEach(gateway => {
        if (!nodes.some(n => n.id === gateway.name)) {
          nodes.push({
            id: gateway.name,
            label: gateway.name,
            type: "gateway"
          });
          
          links.push({
            source: gateway.name,
            target: "service",
            type: "gateway",
            weight: null
          });
        }
      });
    }
    
    // 添加出站连接
    if (details.dataPlane && details.dataPlane.outbound && details.dataPlane.outbound.length > 0) {
      details.dataPlane.outbound.forEach(outbound => {
        if (!nodes.some(n => n.id === outbound.service)) {
          nodes.push({
            id: outbound.service,
            label: outbound.service,
            type: "outbound"
          });
          
          links.push({
            source: "service",
            target: outbound.service,
            type: "outbound",
            port: outbound.port
          });
        }
      });
    }
    
    // 创建力导向布局
    const simulation = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(links).id(d => d.id).distance(100))
      .force("charge", d3.forceManyBody().strength(-800))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .on("tick", ticked);
    
    // 绘制连接线
    const link = svg.append("g")
      .attr("class", "links")
      .selectAll("g")
      .data(links)
      .enter()
      .append("g");
    
    // 连接线
    link.append("line")
      .attr("stroke", d => {
        if (d.type === "subset") return "#2ca02c";
        if (d.type === "gateway") return "#ff7f0e";
        return "#999";
      })
      .attr("stroke-width", 1.5)
      .attr("stroke-dasharray", d => d.type === "subset" ? "5,5" : "");
      
    // 权重标签
    link.append("text")
      .attr("dy", -5)
      .attr("text-anchor", "middle")
      .attr("fill", "green")
      .style("font-weight", "bold")
      .text(d => {
        if (d.weight !== null && d.weight !== undefined && d.weight > 0) {
          return `${d.weight}%`;
        }
        return '';
      });
    
    // 端口标签
    link.append("text")
      .attr("dy", 15)
      .attr("text-anchor", "middle")
      .text(d => d.port ? `port: ${d.port}` : '');
    
    // 节点
    const node = svg.append("g")
      .attr("class", "nodes")
      .selectAll("g")
      .data(nodes)
      .enter()
      .append("g")
      .call(d3.drag()
        .on("start", dragstarted)
        .on("drag", dragged)
        .on("end", dragended));
    
    // 绘制不同类型的节点
    node.each(function(d) {
      const g = d3.select(this);
      
      if (d.type === "service") {
        g.append("circle")
          .attr("r", 25)
          .attr("fill", "#69b3a2");
      } else if (d.type === "subset") {
        g.append("rect")
          .attr("x", -20)
          .attr("y", -20)
          .attr("width", 40)
          .attr("height", 40)
          .attr("fill", "#2ca02c");
      } else if (d.type === "gateway") {
        g.append("polygon")
          .attr("points", "0,-25 20,10 -20,10")
          .attr("fill", "#ff7f0e");
      } else {
        g.append("circle")
          .attr("r", 15)
          .attr("fill", "#d62728");
      }
      
      // 添加标签
      const labels = d.label.split('\n');
      labels.forEach((text, i) => {
        g.append("text")
          .attr("dy", i * 20 - 5 * (labels.length - 1))
          .attr("text-anchor", "middle")
          .text(text);
      });
    });
    
    function ticked() {
      link.select("line")
        .attr("x1", d => d.source.x)
        .attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x)
        .attr("y2", d => d.target.y);
        
      link.select("text")
        .attr("x", d => (d.source.x + d.target.x) / 2)
        .attr("y", d => (d.source.y + d.target.y) / 2);
        
      node.attr("transform", d => `translate(${d.x},${d.y})`);
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
      d.fx = null;
      d.fy = null;
    }
  };
  
  return (
    <div className="data-plane-graph">
      <h3>数据平面配置图</h3>
      <div className="legend">
        <div className="legend-item">
          <svg width="20" height="20">
            <circle cx="10" cy="10" r="8" fill="#69b3a2"/>
          </svg>
          <span>数据平面实际配置</span>
        </div>
        <div className="legend-item">
          <svg width="20" height="20">
            <rect x="2" y="2" width="16" height="16" fill="#2ca02c"/>
          </svg>
          <span>仅在控制平面配置的版本</span>
        </div>
        <div className="legend-item">
          <svg width="20" height="20">
            <polygon points="10,2 16,16 4,16" fill="#ff7f0e"/>
          </svg>
          <span>网关</span>
        </div>
        <div className="legend-item">
          <svg width="30" height="20">
            <line x1="5" y1="10" x2="25" y2="10" stroke="#2ca02c" strokeWidth="2" strokeDasharray="5,5"/>
          </svg>
          <span>权重配置差异</span>
        </div>
      </div>
      <svg ref={svgRef} width="100%" height="300" />
    </div>
  );
};

// 添加到全局对象中以便主应用使用
if (typeof window !== 'undefined') {
  window.DataPlaneGraph = DataPlaneGraph;
} 
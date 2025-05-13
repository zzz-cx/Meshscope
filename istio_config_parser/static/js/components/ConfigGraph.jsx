// 使用 window 对象定义组件
window.ConfigGraph = ({ serviceDetails }) => {
  const svgRef = React.useRef(null);

  React.useEffect(() => {
    if (!serviceDetails || !serviceDetails.relations) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const svgNode = svg.node();
    const width = svgNode.clientWidth || svgNode.parentNode.clientWidth || 300;
    const height = svgNode.clientHeight || svgNode.parentNode.clientHeight || 200;

    // 创建节点和连接
    const nodes = [];
    const links = [];

    const relations = serviceDetails.relations;
    const configs = serviceDetails.configurations || {};
    const mainServiceName = serviceDetails.name || 'service';

    console.log("ConfigGraph - Service details:", serviceDetails);

    // 添加主服务节点
    nodes.push({
      id: mainServiceName,
      name: mainServiceName,
      type: 'service'
    });

    // 获取从VirtualService配置的权重信息
    const weightInfo = {};
    
    // 直接从configurations.weights获取权重信息
    if (configs.weights) {
      console.log("ConfigGraph - Found weights in configurations:", configs.weights);
      Object.entries(configs.weights).forEach(([subset, weightData]) => {
        if (weightData && weightData.weight !== undefined) {
          console.log(`ConfigGraph - Found weight in config for ${subset}: ${weightData.weight}`);
          weightInfo[subset] = weightData.weight;
        }
      });
    }
    
    // 如果需要，也可以从VirtualService配置中获取权重
    if (configs.virtualServices && configs.virtualServices.length > 0) {
      configs.virtualServices.forEach(vs => {
        console.log("ConfigGraph - Processing VS:", vs);
        if (vs.http) {
          vs.http.forEach(route => {
            if (route.route) {
              route.route.forEach(dest => {
                if (dest.destination && dest.destination.subset && dest.weight !== undefined) {
                  console.log(`ConfigGraph - Found weight for ${dest.destination.subset}: ${dest.weight}`);
                  weightInfo[dest.destination.subset] = dest.weight;
                }
              });
            }
          });
        }
      });
    }

    console.log("ConfigGraph - Weight info:", weightInfo);

    // 添加子集节点和权重连接
    if (relations.subsets && Array.isArray(relations.subsets)) {
      relations.subsets.forEach(subset => {
        const subsetId = `${mainServiceName}-${subset.name}`;
        nodes.push({
          id: subsetId,
          name: subset.name,
          version: subset.version,
          type: 'subset'
        });
        
        // 使用从VirtualService获取的权重
        const weight = weightInfo[subset.name] !== undefined ? weightInfo[subset.name] : 0;
        
        links.push({
          source: mainServiceName,
          target: subsetId,
          type: 'subset',
          label: weight > 0 ? `${weight}%` : '',
          weight: weight
        });
      });
    }

    // 处理限流规则
    if (relations.rateLimit && Array.isArray(relations.rateLimit)) {
      relations.rateLimit.forEach(rule => {
        if (rule.conditions && Array.isArray(rule.conditions)) {
          rule.conditions.forEach(condition => {
            if (condition.type === 'header' && 
                condition.name === 'x-request-source' && 
                condition.value) {
              const sourceService = condition.value;
              if (!nodes.find(n => n.id === sourceService)) {
                nodes.push({
                  id: sourceService,
                  name: sourceService,
                  type: 'source'
                });
              }
              links.push({
                source: sourceService,
                target: mainServiceName,
                type: 'rateLimit',
                label: `${rule.requests_per_unit} req/${rule.unit}`
              });
            }
          });
        }
      });
    }
    
    // 处理熔断规则
    if (configs.circuitBreaker && 
        (configs.circuitBreaker.global_ || 
        (configs.circuitBreaker.subsets && 
         Object.keys(configs.circuitBreaker.subsets).length > 0))) {
      console.log("ConfigGraph - Found circuit breaker config:", configs.circuitBreaker);
      
      // 添加熔断配置节点
      const circuitBreakerId = `${mainServiceName}-cb`;
      nodes.push({
        id: circuitBreakerId,
        name: "熔断配置",
        type: 'circuit-breaker'
      });
      
      // 创建主服务到熔断配置的连接
      links.push({
        source: mainServiceName,
        target: circuitBreakerId,
        type: 'circuit-breaker',
        label: '熔断保护'
      });
      
      // 如果有子集特定的熔断配置，为它们创建连接
      if (configs.circuitBreaker.subsets) {
        Object.entries(configs.circuitBreaker.subsets).forEach(([subsetName, cbConfig]) => {
          // 检查子集配置是否为null
          if (cbConfig === null) return;
          
          const subsetId = `${mainServiceName}-${subsetName}`;
          // 检查该子集节点是否存在
          if (nodes.find(n => n.id === subsetId)) {
            links.push({
              source: circuitBreakerId,
              target: subsetId,
              type: 'circuit-breaker-subset',
              label: '子集熔断'
            });
          }
        });
      }
    }

    // 只有当有节点时才创建力导向布局
    if (nodes.length > 0) {
      const simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(links).id(d => d.id).distance(100))
        .force('charge', d3.forceManyBody().strength(-300))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide().radius(40));

      // 创建箭头标记
      svg.append("defs").selectAll("marker")
        .data(["rateLimit", "subset", "circuit-breaker", "circuit-breaker-subset"])
        .enter().append("marker")
        .attr("id", d => `arrow-${d}`)
        .attr("viewBox", "0 -5 10 10")
        .attr("refX", 15)
        .attr("refY", 0)
        .attr("markerWidth", 6)
        .attr("markerHeight", 6)
        .attr("orient", "auto")
        .append("path")
        .attr("d", "M0,-5L10,0L0,5")
        .attr("class", d => `arrow-${d}`);

      // 绘制连接线和标签
      const linkGroup = svg.append("g")
        .selectAll("g")
        .data(links)
        .enter().append("g")
        .attr("class", "link-group");

      linkGroup.append("line")
        .attr("class", d => `link link-${d.type}`)
        .attr("marker-end", d => `url(#arrow-${d.type})`);

      linkGroup.append("text")
        .attr("class", "link-label")
        .attr("dy", -5)
        .text(d => d.label);

      // 绘制节点
      const node = svg.append("g")
        .selectAll("g")
        .data(nodes)
        .enter().append("g")
        .attr("class", d => `node node-${d.type}`);

      // 为每种节点类型创建不同的形状
      node.each(function(d) {
        const thisNode = d3.select(this);
        if (d.type === 'circuit-breaker') {
          // 熔断器使用八边形
          thisNode.append("polygon")
            .attr("points", "0,-8 6,-6 8,0 6,6 0,8 -6,6 -8,0 -6,-6")
            .attr("class", "cb-shape");
        } else {
          // 其他节点使用圆形
          thisNode.append("circle")
            .attr("r", 8);
        }
      });

      // 添加节点标签
      const labels = node.append("text")
        .attr("dx", 12)
        .attr("dy", ".35em")
        .attr("class", "node-label");

      labels.append("tspan")
        .text(d => d.name)
        .attr("x", 12);

      // 为子集节点添加版本标签
      labels.filter(d => d.type === 'subset')
        .append("tspan")
        .text(d => `(v${d.version})`)
        .attr("x", 12)
        .attr("dy", "1.2em")
        .attr("class", "version-label");

      // 更新力导向布局
      simulation.on("tick", () => {
        linkGroup.selectAll("line")
          .attr("x1", d => d.source.x)
          .attr("y1", d => d.source.y)
          .attr("x2", d => d.target.x)
          .attr("y2", d => d.target.y);

        linkGroup.selectAll("text")
          .attr("x", d => (d.source.x + d.target.x) / 2)
          .attr("y", d => (d.source.y + d.target.y) / 2);

        node.attr("transform", d => `translate(${d.x},${d.y})`);
      });

      // 添加拖拽行为
      node.call(d3.drag()
        .on("start", (event) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          event.subject.fx = event.subject.x;
          event.subject.fy = event.subject.y;
        })
        .on("drag", (event) => {
          event.subject.fx = event.x;
          event.subject.fy = event.y;
        })
        .on("end", (event) => {
          if (!event.active) simulation.alphaTarget(0);
          event.subject.fx = null;
          event.subject.fy = null;
        }));
    }

  }, [serviceDetails]);

  return (
    <div className="config-graph">
      <svg ref={svgRef} width="100%" height="100%"></svg>
    </div>
  );
}; 
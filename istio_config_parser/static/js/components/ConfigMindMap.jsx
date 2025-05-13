window.ConfigMindMap = ({ config }) => {
  const svgRef = React.useRef(null);
  const [collapsedNodes, setCollapsedNodes] = React.useState(new Set());
  const [isExpanded, setIsExpanded] = React.useState(false);

  React.useEffect(() => {
    if (!config) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const svgNode = svg.node();
    const width = svgNode.clientWidth || svgNode.parentNode.clientWidth;
    const height = svgNode.clientHeight || svgNode.parentNode.clientHeight;
    const padding = 40;
    const nodeHeight = 25;
    const levelWidth = 160;

    // 创建容器组
    const container = svg.append("g")
      .attr("class", "container");

    // 创建缩放行为
    const zoom = d3.zoom()
      .scaleExtent([0.5, 2])
      .on("zoom", (event) => {
        container.attr("transform", event.transform);
      });

    svg.call(zoom);

    // 创建思维导图数据结构
    const createMindMapData = (obj, name, path = "") => {
      if (!obj) return null;  // 添加空值检查
      
      const node = { 
        name: name || 'root', 
        path,
        children: [],
        originalData: obj,
        id: path || name
      };
      
      if (obj && typeof obj === 'object') {
        if (Array.isArray(obj)) {
          obj.forEach((item, index) => {
            const child = createMindMapData(item, `[${index}]`, `${path}[${index}]`);
            if (child) node.children.push(child);
          });
        } else {
          Object.entries(obj).forEach(([key, value]) => {
            const childPath = path ? `${path}.${key}` : key;
            if (value !== undefined && value !== null) {
              if (typeof value === 'object') {
                const child = createMindMapData(value, key, childPath);
                if (child) node.children.push(child);
              } else {
                node.children.push({ 
                  name: `${key}: ${value}`, 
                  path: childPath,
                  id: childPath
                });
              }
            }
          });
        }
      }
      return node;
    };

    // 计算节点位置
    const calculateLayout = (node, level = 0, startY = 0) => {
      if (!node) return startY;  // 添加空值检查

      node.x = level * levelWidth;
      node.y = startY;
      
      if (!collapsedNodes.has(node.id) && node.children && node.children.length > 0) {
        let currentY = startY;
        node.children.forEach(child => {
          currentY = calculateLayout(child, level + 1, currentY);
          currentY += nodeHeight;
        });
        if (node.children.length > 0) {
          node.y = startY + (currentY - startY - nodeHeight) / 2;
        }
        return currentY;
      }
      return startY + nodeHeight;
    };

    // 渲染连接线
    const renderLinks = (node) => {
      if (!node || !node.children) return;  // 添加空值检查
      
      if (!collapsedNodes.has(node.id) && node.children) {
        node.children.forEach(child => {
          if (child.x !== undefined && child.y !== undefined && 
              node.x !== undefined && node.y !== undefined) {  // 添加坐标检查
            container.append("path")
              .attr("class", "mindmap-link")
              .attr("d", `M${node.x},${node.y}L${child.x},${child.y}`);
            renderLinks(child);
          }
        });
      }
    };

    // 渲染节点
    const renderNodes = (node) => {
      if (!node || node.x === undefined || node.y === undefined) return;  // 添加空值检查

      const g = container.append("g")
        .attr("class", "mindmap-node")
        .attr("transform", `translate(${node.x},${node.y})`);

      g.append("circle")
        .attr("class", "mindmap-node-circle")
        .attr("r", 4);

      // 添加展开/折叠指示器
      if (node.children && node.children.length > 0) {
        const indicator = g.append("g")
          .attr("class", "collapse-indicator-group")
          .style("cursor", "pointer")
          .on("click", (event) => {
            event.stopPropagation();
            setCollapsedNodes(prev => {
              const next = new Set(prev);
              if (next.has(node.id)) {
                next.delete(node.id);
              } else {
                next.add(node.id);
              }
              return next;
            });
          });

        indicator.append("circle")
          .attr("class", "collapse-indicator")
          .attr("r", 6)
          .attr("cx", -10)
          .attr("cy", 0);

        indicator.append("text")
          .attr("class", "collapse-icon")
          .attr("x", -10)
          .attr("y", 4)
          .attr("text-anchor", "middle")
          .style("font-size", "12px")
          .style("pointer-events", "none")
          .text(collapsedNodes.has(node.id) ? "+" : "-");
      }

      g.append("text")
        .attr("x", 8)
        .attr("y", 4)
        .text(node.name)
        .attr("class", "node-text");

      if (!collapsedNodes.has(node.id) && node.children) {
        node.children.forEach(child => renderNodes(child));
      }
    };

    const rootData = createMindMapData(config, config.kind || 'Config');
    if (rootData) {  // 添加空值检查
      calculateLayout(rootData);
      renderLinks(rootData);
      renderNodes(rootData);

      // 计算边界并调整视图
      const bounds = container.node().getBBox();
      const scale = Math.min(
        (width - padding * 2) / (bounds.width || 1),
        (height - padding * 2) / (bounds.height || 1),
        1
      );

      const xOffset = (width - (bounds.width || 0) * scale) / 2;
      const yOffset = (height - (bounds.height || 0) * scale) / 2;

      container.attr("transform", `translate(${xOffset},${yOffset}) scale(${scale})`);
    }

  }, [config, collapsedNodes]);

  const toggleExpand = () => {
    setIsExpanded(!isExpanded);
    if (!isExpanded) {
      const overlay = document.createElement('div');
      overlay.className = 'graph-overlay';
      overlay.id = 'config-mindmap-overlay';
      overlay.onclick = () => {
        setIsExpanded(false);
        overlay.remove();
      };
      document.body.appendChild(overlay);
      setTimeout(() => overlay.classList.add('visible'), 0);
    } else {
      const overlay = document.querySelector('#config-mindmap-overlay');
      if (overlay) {
        overlay.classList.remove('visible');
        setTimeout(() => overlay.remove(), 300);
      }
    }
  };

  return (
    <div className={`graph-container config-mindmap ${isExpanded ? 'expanded' : ''}`}>
      <h4>配置结构图</h4>
      <button className="expand-button" onClick={toggleExpand}>
        {isExpanded ? '收起' : '放大'}
      </button>
      <svg ref={svgRef} width="100%" height="100%"></svg>
    </div>
  );
}; 
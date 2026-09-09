#!/usr/bin/env python3
"""
流量生成器模块
用于生成测试流量和模拟用户行为
"""

import asyncio
import aiohttp
import time
import random
from typing import Dict, List, Any
from datetime import datetime
import logging

class TrafficGenerator:
    """流量生成器"""
    
    def __init__(self, config: Dict[str, Any]):
        """初始化流量生成器"""
        self.config = config
        self.session = None
        self.active_tasks = []
        self.logger = logging.getLogger(__name__)
        
        # 从配置获取基础URL
        self.base_url = config['environment']['cluster_config']['ingress_url']
        
    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.stop_all_traffic()
        if self.session:
            await self.session.close()
    
    async def start_traffic(self, traffic_config: Dict[str, Any], duration: int):
        """开始生成流量"""
        qps = traffic_config.get('qps', 1)
        concurrent_users = traffic_config.get('concurrent_users', 1)
        target_endpoint = traffic_config.get('target_endpoint', '/')
        
        self.logger.info(f"开始生成流量: QPS={qps}, 并发用户={concurrent_users}, 持续时间={duration}s")
        
        # 计算每个用户的请求间隔
        interval = concurrent_users / qps if qps > 0 else 1
        
        # 启动多个并发用户
        for user_id in range(concurrent_users):
            task = asyncio.create_task(
                self._user_traffic_loop(user_id, target_endpoint, interval, duration)
            )
            self.active_tasks.append(task)
        
        # 等待所有任务完成
        await asyncio.gather(*self.active_tasks, return_exceptions=True)
        self.active_tasks.clear()
    
    async def continue_traffic(self, additional_duration: int):
        """继续生成流量指定时间"""
        if not self.active_tasks:
            self.logger.warning("没有活跃的流量生成任务")
            return
        
        # 延长现有任务的运行时间
        await asyncio.sleep(additional_duration)
    
    async def stop_all_traffic(self):
        """停止所有流量生成"""
        for task in self.active_tasks:
            if not task.done():
                task.cancel()
        
        if self.active_tasks:
            await asyncio.gather(*self.active_tasks, return_exceptions=True)
        self.active_tasks.clear()
        
        self.logger.info("所有流量生成已停止")
    
    async def _user_traffic_loop(self, user_id: int, endpoint: str, interval: float, duration: int):
        """单个用户的流量生成循环"""
        start_time = time.time()
        request_count = 0
        
        while time.time() - start_time < duration:
            try:
                # 发送请求
                await self._send_request(user_id, endpoint)
                request_count += 1
                
                # 等待下一个请求
                await asyncio.sleep(interval + random.uniform(-0.1, 0.1))  # 添加少量随机性
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"用户 {user_id} 请求失败: {e}")
                await asyncio.sleep(1)  # 错误后等待1秒再继续
        
        self.logger.info(f"用户 {user_id} 完成，共发送 {request_count} 个请求")
    
    async def _send_request(self, user_id: int, endpoint: str):
        """发送单个HTTP请求"""
        url = f"{self.base_url.rstrip('/')}{endpoint}"
        headers = {
            'User-Agent': f'DynamicTester/1.0 (User-{user_id})',
            'X-Request-Source': f'user-{user_id}',
            'X-Test-Timestamp': datetime.now().isoformat()
        }
        
        # 添加一些随机的用户标识
        if random.random() < 0.3:  # 30%的请求带用户身份
            headers['end-user'] = random.choice(['jason', 'alice', 'bob', 'charlie'])
        
        try:
            async with self.session.get(url, headers=headers) as response:
                content = await response.text()
                
                # 记录请求结果
                self.logger.debug(f"用户 {user_id} 请求 {url}: {response.status}")
                
                # 可以在这里添加响应内容的验证
                if response.status >= 400:
                    self.logger.warning(f"请求失败: {response.status} - {url}")
                
                return {
                    'user_id': user_id,
                    'url': url,
                    'status_code': response.status,
                    'response_time': response.headers.get('X-Response-Time'),
                    'timestamp': datetime.now().isoformat()
                }
                
        except asyncio.TimeoutError:
            self.logger.warning(f"用户 {user_id} 请求超时: {url}")
            raise
        except Exception as e:
            self.logger.error(f"用户 {user_id} 请求异常: {e}")
            raise
    
    async def generate_specific_pattern(self, pattern_config: Dict[str, Any]):
        """生成特定的流量模式"""
        pattern_type = pattern_config.get('type', 'constant')
        
        if pattern_type == 'burst':
            await self._generate_burst_pattern(pattern_config)
        elif pattern_type == 'ramp_up':
            await self._generate_ramp_up_pattern(pattern_config)
        elif pattern_type == 'spike':
            await self._generate_spike_pattern(pattern_config)
        else:
            # 默认恒定流量模式
            await self.start_traffic(pattern_config, pattern_config.get('duration', 60))
    
    async def _generate_burst_pattern(self, config: Dict[str, Any]):
        """生成突发流量模式"""
        burst_qps = config.get('burst_qps', 50)
        burst_duration = config.get('burst_duration', 10)
        burst_interval = config.get('burst_interval', 60)
        total_duration = config.get('total_duration', 300)
        
        start_time = time.time()
        
        while time.time() - start_time < total_duration:
            # 突发期间
            self.logger.info(f"开始突发流量: {burst_qps} QPS")
            await self.start_traffic({
                'qps': burst_qps,
                'concurrent_users': min(burst_qps, 20),
                'target_endpoint': config.get('target_endpoint', '/')
            }, burst_duration)
            
            # 休息期间
            remaining_time = total_duration - (time.time() - start_time)
            sleep_time = min(burst_interval - burst_duration, remaining_time)
            
            if sleep_time > 0:
                self.logger.info(f"突发流量休息: {sleep_time}s")
                await asyncio.sleep(sleep_time)
    
    async def _generate_ramp_up_pattern(self, config: Dict[str, Any]):
        """生成递增流量模式"""
        start_qps = config.get('start_qps', 1)
        end_qps = config.get('end_qps', 20)
        ramp_duration = config.get('ramp_duration', 300)
        step_duration = config.get('step_duration', 30)
        
        steps = ramp_duration // step_duration
        qps_increment = (end_qps - start_qps) / steps
        
        current_qps = start_qps
        
        for step in range(steps):
            self.logger.info(f"递增流量第 {step+1} 步: {current_qps:.1f} QPS")
            
            await self.start_traffic({
                'qps': current_qps,
                'concurrent_users': min(int(current_qps), 10),
                'target_endpoint': config.get('target_endpoint', '/')
            }, step_duration)
            
            current_qps += qps_increment
    
    async def _generate_spike_pattern(self, config: Dict[str, Any]):
        """生成尖峰流量模式"""
        normal_qps = config.get('normal_qps', 5)
        spike_qps = config.get('spike_qps', 100)
        spike_duration = config.get('spike_duration', 30)
        total_duration = config.get('total_duration', 300)
        
        # 正常流量阶段
        normal_duration = (total_duration - spike_duration) // 2
        
        # 第一阶段：正常流量
        self.logger.info(f"尖峰测试 - 正常流量阶段1: {normal_qps} QPS")
        await self.start_traffic({
            'qps': normal_qps,
            'concurrent_users': max(normal_qps, 2),
            'target_endpoint': config.get('target_endpoint', '/')
        }, normal_duration)
        
        # 第二阶段：尖峰流量
        self.logger.info(f"尖峰测试 - 尖峰流量阶段: {spike_qps} QPS")
        await self.start_traffic({
            'qps': spike_qps,
            'concurrent_users': min(spike_qps, 50),
            'target_endpoint': config.get('target_endpoint', '/')
        }, spike_duration)
        
        # 第三阶段：恢复正常
        self.logger.info(f"尖峰测试 - 正常流量阶段2: {normal_qps} QPS")
        await self.start_traffic({
            'qps': normal_qps,
            'concurrent_users': max(normal_qps, 2),
            'target_endpoint': config.get('target_endpoint', '/')
        }, normal_duration)
    
    async def simulate_user_behavior(self, behavior_config: Dict[str, Any]):
        """模拟真实用户行为"""
        user_flows = behavior_config.get('user_flows', [])
        concurrent_users = behavior_config.get('concurrent_users', 5)
        
        # 为每个用户创建一个行为流
        tasks = []
        for user_id in range(concurrent_users):
            task = asyncio.create_task(
                self._simulate_single_user_flow(user_id, user_flows)
            )
            tasks.append(task)
        
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _simulate_single_user_flow(self, user_id: int, user_flows: List[Dict[str, Any]]):
        """模拟单个用户的行为流"""
        for flow in user_flows:
            try:
                # 用户思考时间
                think_time = flow.get('think_time', 2)
                await asyncio.sleep(random.uniform(think_time * 0.5, think_time * 1.5))
                
                # 执行用户操作
                endpoint = flow.get('endpoint', '/')
                await self._send_request(user_id, endpoint)
                
                # 操作间隔
                if 'interval' in flow:
                    await asyncio.sleep(flow['interval'])
                    
            except Exception as e:
                self.logger.error(f"用户 {user_id} 行为流执行失败: {e}")
                continue

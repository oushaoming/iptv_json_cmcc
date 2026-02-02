import json
import os
import sys
import requests
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from urllib.parse import urlparse
from datetime import datetime

# 配置文件路径
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'iptv_config.json')

class IPTV2M3U:
    def __init__(self):
        self.channels = []

    def load_json(self, json_file):
        """从JSON文件加载频道数据"""
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            print(f"JSON数据加载成功，类型: {type(data)}")

            # 检查不同的JSON结构
            if isinstance(data, dict) and 'channels' in data:
                self.channels = data['channels']
                print(f"找到 {len(self.channels)} 个频道")
                return True
            elif isinstance(data, list):
                self.channels = data
                print(f"直接找到频道列表，共 {len(self.channels)} 个频道")
                return True
            else:
                print(f"未知的JSON结构: {type(data)}")
                return False
        except Exception as e:
            print(f"加载JSON文件失败: {e}")
            return False

    def _get_phychannels(self, channel):
        """获取物理频道列表，兼容两种JSON格式"""
        # 检查是否有phychannels字段（getAllChannel2.json格式）
        if 'phychannels' in channel and isinstance(channel['phychannels'], list):
            return channel['phychannels']
        # 直接返回包含params的当前频道作为单一物理频道（getAllChannel.json格式）
        elif 'params' in channel:
            # 创建一个虚拟的phychannel对象
            virtual_phychannel = {
                'bitrateType': channel.get('bitrateType', ''),
                'bitrateTypeName': channel.get('bitrateTypeName', ''),
                'params': channel['params']
            }
            return [virtual_phychannel]
        # 尝试直接从channel中提取必要信息创建虚拟phychannel
        else:
            virtual_phychannel = {
                'bitrateType': channel.get('bitrateType', ''),
                'bitrateTypeName': channel.get('bitrateTypeName', ''),
                'params': channel  # 使用整个channel作为params
            }
            return [virtual_phychannel]

    def _sort_phychannels_by_quality(self, phychannels, quality_preference):
        """根据画质偏好排序物理频道"""
        quality_order = {
            'ultra_high': ['4K', '超高清', 'UHD', '2160p'],
            'high': ['高清', 'HD', '1080p'],
            'standard': ['标清', 'SD', '720p', '480p']
        }

        def get_quality_score(phychannel):
            # 默认最低优先级
            score = 100
            bitrate_type_name = phychannel.get('bitrateTypeName', '').lower()
            bitrate_type = phychannel.get('bitrateType', '')

            # 根据偏好设置优先级
            target_key = 'high'  # 默认高清
            if quality_preference == 'ultra_high':
                target_key = 'ultra_high'
            elif quality_preference == 'standard':
                target_key = 'standard'

            # 检查目标画质关键词
            for i, keyword in enumerate(quality_order.get(target_key, [])):
                if keyword.lower() in bitrate_type_name or keyword in bitrate_type:
                    score = i  # 匹配目标画质，分数越低优先级越高
                    return score

            # 检查其他画质关键词
            for key, keywords in quality_order.items():
                if key == target_key:
                    continue
                for i, keyword in enumerate(keywords):
                    if keyword.lower() in bitrate_type_name or keyword in bitrate_type:
                        score = len(quality_order[target_key]) + i  # 非目标画质，分数高于目标画质
                        return score

            return score

        # 按画质分数排序
        return sorted(phychannels, key=get_quality_score)

    def _check_quality(self, phychannel, target_quality):
        """检查物理频道是否符合目标画质"""
        if target_quality == 'any':
            return True

        bitrate_type_name = phychannel.get('bitrateTypeName', '').lower()
        bitrate_type = phychannel.get('bitrateType', '')

        quality_keywords = {
            'ultra_high': ['4K', '超高清', 'UHD', '2160p'],
            'high': ['高清', 'HD', '1080p'],
            'standard': ['标清', 'SD', '720p', '480p']
        }

        # 检查是否包含目标画质关键词
        for keyword in quality_keywords.get(target_quality, []):
            if keyword.lower() in bitrate_type_name or keyword in bitrate_type:
                return True

        return False

    def _get_target_quality_code(self, quality_preference):
        """根据画质偏好获取目标画质代码"""
        if quality_preference == 'high':
            return ['4', '40']  # 高清
        elif quality_preference == 'standard':
            return ['2']  # 标清
        elif quality_preference == 'ultra_high':
            return ['6', '10', '14']  # 超高清、4K、4K超高清
        return []

    def _check_quality(self, phychannel, target_quality_codes):
        """检查物理频道是否符合目标画质"""
        bitrate_type = phychannel.get('bitrateType', '')
        return bitrate_type in target_quality_codes

    def _get_bitrate_type(self, bitrate_code):
        """根据bitrate code获取画质类型"""
        bitrate_map = {
            '2': '标清',
            '4': '高清',
            '40': '高清',
            '6': '超清',
            '10': '4K',
            '14': '4K超高清',
            '': '未知'
        }
        return bitrate_map.get(bitrate_code, '未知')

    def generate_csv(self, output_file, progress_callback=None):
        """生成CSV格式的中间数据文件"""
        if not self.channels:
            print("没有频道数据")
            return False

        print(f"开始生成CSV中间数据，共 {len(self.channels)} 个频道")

        try:
            with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
                # 写入CSV表头
                headers = ['code', 'title', 'channelnum', 'hwurl', 'zteurl', 'bitrateType', 'bitrateTypeName', 'hwmediaid', 'ztecode', 'icon']
                f.write(','.join(headers) + '\n')

                processed_count = 0
                total_channels = len(self.channels)

                for channel in self.channels:
                    # 获取频道基本信息
                    code = channel.get('code', '')
                    title = channel.get('title', 'Unknown')
                    channel_num = channel.get('channelnum', '')
                    icon = channel.get('icon', '')

                    # 获取物理频道列表（兼容两种JSON格式）
                    phychannels = self._get_phychannels(channel)
                    if not phychannels:
                        print(f"频道 {title} 没有物理频道信息")
                        continue

                    # 为每个物理频道生成一行数据
                    for phychannel in phychannels:
                        params = phychannel.get('params', {})
                        hwurl = params.get('hwurl', '')
                        zteurl = params.get('zteurl', '')
                        bitrate_type = phychannel.get('bitrateType', '')
                        bitrate_type_name = phychannel.get('bitrateTypeName', '')
                        ztecode = params.get('ztecode', '')
                        hwmediaid = params.get('hwmediaid', '')

                        # 转义CSV中的逗号和引号
                        def escape_csv(value):
                            if isinstance(value, str):
                                if ',' in value or '"' in value or '\n' in value:
                                    return '"' + value.replace('"', '""') + '"'
                            return str(value)

                        # 构造CSV行
                        row = [
                            escape_csv(code),
                            escape_csv(title),
                            escape_csv(channel_num),
                            escape_csv(hwurl),
                            escape_csv(zteurl),
                            escape_csv(bitrate_type),
                            escape_csv(bitrate_type_name),
                            escape_csv(hwmediaid),
                            escape_csv(ztecode),
                            escape_csv(icon)
                        ]

                        # 写入CSV行
                        f.write(','.join(row) + '\n')

                    processed_count += 1
                    print(f"已处理频道: {title}")

                    # 更新进度
                    if progress_callback:
                        progress_callback(processed_count, total_channels)

                print(f"CSV中间数据生成完成，共处理 {processed_count} 个频道")

            return True

        except Exception as e:
            print(f"生成CSV文件失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    # 修改generate_m3u方法，添加multi_quality参数和多画质输出逻辑
    def generate_m3u(self, output_file, use_zte=True, use_hw=False, quality_preference='high', progress_callback=None, udp_proxy='', multi_quality=False):
        """生成M3U播放列表"""
        if not self.channels:
            print("没有频道数据")
            return False

        print(f"开始生成M3U，共 {len(self.channels)} 个频道")

        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write('#EXTM3U\n')

                processed_count = 0
                total_channels = len(self.channels)

                for channel in self.channels:
                    # 获取频道基本信息
                    title = channel.get('title', 'Unknown')
                    channel_num = channel.get('channelnum', '')
                    icon = channel.get('icon', '')

                    # 获取物理频道列表（兼容两种JSON格式）
                    phychannels = self._get_phychannels(channel)
                    if not phychannels:
                        print(f"频道 {title} 没有物理频道信息")
                        continue

                    print(f"频道 {title} 有 {len(phychannels)} 个物理频道")

                    # 根据画质偏好排序物理频道
                    sorted_phychannels = self._sort_phychannels_by_quality(phychannels, quality_preference)

                    if multi_quality:
                        # 多画质模式：保留所有可用的物理频道
                        filtered_phychannels = []
                        for phychannel in sorted_phychannels:
                            params = phychannel.get('params', {})
                            if (use_zte and params.get('zteurl')) or (use_hw and params.get('hwurl')):
                                filtered_phychannels.append(phychannel)

                        # 如果没有找到符合条件的频道，尝试使用第一个可用的流
                        if not filtered_phychannels:
                            for phychannel in sorted_phychannels:
                                params = phychannel.get('params', {})
                                for key, value in params.items():
                                    if key.endswith('url') and value and value.startswith(('rtp://', 'udp://', 'http://', 'https://')):
                                        filtered_phychannels.append(phychannel)
                                        break
                                if filtered_phychannels:
                                    break

                        for phychannel in filtered_phychannels:
                            params = phychannel.get('params', {})
                            stream_url = None

                            # 选择适当的流URL
                            if use_zte and params.get('zteurl'):
                                stream_url = params['zteurl'].strip()
                            elif use_hw and params.get('hwurl'):
                                stream_url = params['hwurl'].strip()
                            else:
                                # 尝试其他可能的URL字段
                                for key, value in params.items():
                                    if key.endswith('url') and value and value.startswith(('rtp://', 'udp://', 'http://', 'https://')):
                                        stream_url = value.strip()
                                        break

                            if not stream_url:
                                continue

                            # 获取画质信息
                            bitrate_type = phychannel.get('bitrateTypeName', '未知')
                            if not bitrate_type or bitrate_type == '未知':
                                bitrate_type = self._get_bitrate_type(phychannel.get('bitrateType', ''))

                            # 根据udp_proxy参数处理stream_url
                            if udp_proxy:
                                # 处理 rtp:// 和 udp://
                                stream_url = stream_url.replace('rtp://', 'rtp/').replace('udp://', 'udp/')
                                stream_url = f"http://{udp_proxy}/{stream_url}"

                            # 写入M3U条目
                            extinf_line = f'#EXTINF:-1 tvg-id="{channel.get("code", "")}" tvg-name="{title}"'
                            if channel_num:
                                extinf_line += f' tvg-chno="{channel_num}"'
                            if icon:
                                extinf_line += f' tvg-logo="{icon}"'
                            extinf_line += f' group-title="IPTV",{title} ({bitrate_type})\n'

                            f.write(extinf_line)
                            f.write(f'{stream_url}\n')

                            processed_count += 1
                            print(f"成功添加频道: {title} ({bitrate_type})")

                            # 更新进度
                            if progress_callback:
                                progress_callback(processed_count, total_channels)
                    else:
                        # 单画质模式：选择第一个可用的物理频道
                        selected_phy = None
                        stream_url = None
                        target_quality = self._get_target_quality_code(quality_preference)

                        for phychannel in sorted_phychannels:
                            params = phychannel.get('params', {})
                            print(f"物理频道参数: {params}")

                            # 检查当前物理频道是否符合目标画质
                            if self._check_quality(phychannel, target_quality):
                                if use_zte and params.get('zteurl'):
                                    selected_phy = phychannel
                                    stream_url = params['zteurl']
                                    # 去除 URL 前后空格
                                    stream_url = stream_url.strip()
                                    print(f"使用ZTE流: {stream_url}")
                                    break
                                elif use_hw and params.get('hwurl'):
                                    selected_phy = phychannel
                                    stream_url = params['hwurl']
                                    # 去除 URL 前后空格
                                    stream_url = stream_url.strip()
                                    print(f"使用HW流: {stream_url}")
                                    break
                                else:
                                    # 尝试其他可能的URL字段
                                    for key, value in params.items():
                                        if key.endswith('url') and value and value.startswith(('rtp://', 'udp://', 'http://', 'https://')):
                                            selected_phy = phychannel
                                            stream_url = value
                                            # 去除 URL 前后空格
                                            stream_url = stream_url.strip()
                                            print(f"使用其他流: {key}={stream_url}")
                                            break
                                    if stream_url:
                                        break

                        if not stream_url:
                            # 如果没找到目标画质的流，尝试选择第一个可用的流
                            for phychannel in sorted_phychannels:
                                params = phychannel.get('params', {})
                                if use_zte and params.get('zteurl'):
                                    selected_phy = phychannel
                                    stream_url = params['zteurl']
                                    # 去除 URL 前后空格
                                    stream_url = stream_url.strip()
                                    print(f"使用ZTE流: {stream_url}")
                                    break
                                elif use_hw and params.get('hwurl'):
                                    selected_phy = phychannel
                                    stream_url = params['hwurl']
                                    # 去除 URL 前后空格
                                    stream_url = stream_url.strip()
                                    print(f"使用HW流: {stream_url}")
                                    break
                                else:
                                    for key, value in params.items():
                                        if key.endswith('url') and value and value.startswith(('rtp://', 'udp://', 'http://', 'https://')):
                                            selected_phy = phychannel
                                            stream_url = value
                                            # 去除 URL 前后空格
                                            stream_url = stream_url.strip()
                                            print(f"使用其他流: {key}={stream_url}")
                                            break
                                    if stream_url:
                                        break

                        if not stream_url:
                            print(f"频道 {title} 没有找到可用的流地址")
                            continue

                        # 获取画质信息，直接从选中的物理频道获取
                        if selected_phy:
                            bitrate_type = selected_phy.get('bitrateTypeName', '未知')
                            if not bitrate_type or bitrate_type == '未知':
                                bitrate_type = self._get_bitrate_type(selected_phy.get('bitrateType', ''))
                        else:
                            bitrate_type = '未知'

                        # 根据udp_proxy参数处理stream_url
                        if udp_proxy:
                            # 处理 rtp:// 和 udp://
                            stream_url = stream_url.replace('rtp://', 'rtp/').replace('udp://', 'udp/')
                            stream_url = f"http://{udp_proxy}/{stream_url}"

                        # 写入M3U条目
                        extinf_line = f'#EXTINF:-1 tvg-id="{channel.get("code", "")}" tvg-name="{title}"'
                        if channel_num:
                            extinf_line += f' tvg-chno="{channel_num}"'
                        if icon:
                            extinf_line += f' tvg-logo="{icon}"'
                        extinf_line += f' group-title="IPTV",{title} ({bitrate_type})\n'

                        f.write(extinf_line)
                        f.write(f'{stream_url}\n')

                        processed_count += 1
                        print(f"成功添加频道: {title}")

                        # 更新进度
                        if progress_callback:
                            progress_callback(processed_count, total_channels)

                print(f"M3U生成完成，共添加 {processed_count} 个频道")

            return True

        except Exception as e:
            print(f"生成M3U文件失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    # 修改generate_diyp方法，添加multi_quality参数和多画质输出逻辑
    def generate_diyp(self, output_file, use_zte=True, use_hw=False, quality_preference='high', progress_callback=None, udp_proxy='', multi_quality=False):
        """生成DIYP空壳直播源格式"""
        if not self.channels:
            print("没有频道数据")
            return False

        print(f"开始生成DIYP空壳直播源，共 {len(self.channels)} 个频道")

        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write('IPTV频道,#genre#\n')

                processed_count = 0
                total_channels = len(self.channels)

                for channel in self.channels:
                    title = channel.get('title', 'Unknown')
                    # 获取物理频道列表（兼容两种JSON格式）
                    phychannels = self._get_phychannels(channel)
                    if not phychannels:
                        print(f"频道 {title} 没有物理频道信息")
                        continue

                    # 根据画质偏好排序物理频道
                    sorted_phychannels = self._sort_phychannels_by_quality(phychannels, quality_preference)

                    if multi_quality:
                        # 多画质模式：保留所有可用的物理频道
                        filtered_phychannels = []
                        for phychannel in sorted_phychannels:
                            params = phychannel.get('params', {})
                            if (use_zte and params.get('zteurl')) or (use_hw and params.get('hwurl')):
                                filtered_phychannels.append(phychannel)
                        
                        # 如果没有找到符合条件的频道，尝试使用第一个可用的流
                        if not filtered_phychannels:
                            for phychannel in sorted_phychannels:
                                params = phychannel.get('params', {})
                                for key, value in params.items():
                                    if key.endswith('url') and value and value.startswith(('rtp://', 'udp://', 'http://', 'https://')):
                                        filtered_phychannels.append(phychannel)
                                        break
                                if filtered_phychannels:
                                    break
                        
                        for phychannel in filtered_phychannels:
                            params = phychannel.get('params', {})
                            stream_url = None
                            
                            # 选择适当的流URL
                            if use_zte and params.get('zteurl'):
                                stream_url = params['zteurl'].strip()
                            elif use_hw and params.get('hwurl'):
                                stream_url = params['hwurl'].strip()
                            else:
                                # 尝试其他可能的URL字段
                                for key, value in params.items():
                                    if key.endswith('url') and value and value.startswith(('rtp://', 'udp://', 'http://', 'https://')):
                                        stream_url = value.strip()
                                        break
                            
                            if not stream_url:
                                continue
                            
                            # 获取画质信息
                            bitrate_type = phychannel.get('bitrateTypeName', '未知')
                            if not bitrate_type or bitrate_type == '未知':
                                bitrate_type = self._get_bitrate_type(phychannel.get('bitrateType', ''))
                            
                            if udp_proxy:
                                # 处理 rtp:// 和 udp://
                                stream_url = stream_url.replace('rtp://', 'rtp/').replace('udp://', 'udp/')
                                stream_url = f"http://{udp_proxy}/{stream_url}"
                            
                            line = f"{title},{stream_url}${bitrate_type}\n"
                            f.write(line)
                            
                            processed_count += 1
                            print(f"成功添加频道: {title} ({bitrate_type})")
                            
                            if progress_callback:
                                progress_callback(processed_count, total_channels)
                    else:
                        # 单画质模式：选择第一个可用的物理频道
                        selected_phy = None
                        stream_url = None
                        target_quality = self._get_target_quality_code(quality_preference)

                        for phychannel in sorted_phychannels:
                            params = phychannel.get('params', {})
                            if self._check_quality(phychannel, target_quality):
                                if use_zte and params.get('zteurl'):
                                    selected_phy = phychannel
                                    stream_url = params['zteurl']
                                    # 去除 URL 前后空格
                                    stream_url = stream_url.strip()
                                    break
                                elif use_hw and params.get('hwurl'):
                                    selected_phy = phychannel
                                    stream_url = params['hwurl']
                                    # 去除 URL 前后空格
                                    stream_url = stream_url.strip()
                                    break
                                else:
                                    for key, value in params.items():
                                        if key.endswith('url') and value and value.startswith(('rtp://', 'udp://', 'http://', 'https://')):
                                            selected_phy = phychannel
                                            stream_url = value
                                            # 去除 URL 前后空格
                                            stream_url = stream_url.strip()
                                            break
                                    if stream_url:
                                        break

                        if not stream_url:
                            # 如果没找到目标画质的流，尝试选择第一个可用的流
                            for phychannel in sorted_phychannels:
                                params = phychannel.get('params', {})
                                if use_zte and params.get('zteurl'):
                                    selected_phy = phychannel
                                    stream_url = params['zteurl']
                                    # 去除 URL 前后空格
                                    stream_url = stream_url.strip()
                                    break
                                elif use_hw and params.get('hwurl'):
                                    selected_phy = phychannel
                                    stream_url = params['hwurl']
                                    # 去除 URL 前后空格
                                    stream_url = stream_url.strip()
                                    break
                                else:
                                    for key, value in params.items():
                                        if key.endswith('url') and value and value.startswith(('rtp://', 'udp://', 'http://', 'https://')):
                                            selected_phy = phychannel
                                            stream_url = value
                                            # 去除 URL 前后空格
                                            stream_url = stream_url.strip()
                                            break
                                    if stream_url:
                                        break

                        if not stream_url:
                            print(f"频道 {title} 没有找到可用的流地址")
                            continue

                        # 获取画质信息，直接从选中的物理频道获取
                        if selected_phy:
                            bitrate_type = selected_phy.get('bitrateTypeName', '未知')
                            if not bitrate_type or bitrate_type == '未知':
                                bitrate_type = self._get_bitrate_type(selected_phy.get('bitrateType', ''))
                        else:
                            bitrate_type = '未知'

                        if udp_proxy:
                            # 处理 rtp:// 和 udp://
                            stream_url = stream_url.replace('rtp://', 'rtp/').replace('udp://', 'udp/')
                            stream_url = f"http://{udp_proxy}/{stream_url}"

                        line = f"{title},{stream_url}${bitrate_type}\n"
                        f.write(line)

                        processed_count += 1
                        print(f"成功添加频道: {title}")

                        if progress_callback:
                            progress_callback(processed_count, total_channels)

                print(f"DIYP空壳直播源生成完成，共添加 {processed_count} 个频道")

            return True

        except Exception as e:
            print(f"生成DIYP空壳直播源文件失败: {e}")
            import traceback
            traceback.print_exc()
            return False

class IPTV2M3UGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("IPTV JSON转M3U/DIYP工具 v1.3")
        self.root.geometry("800x600")

        # 临时文件路径
        self.temp_json_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temp_iptv.json')

        # 变量初始化
        self.url_var = tk.StringVar(value="")
        self.output_var = tk.StringVar(value="output.m3u")
        self.status_var = tk.StringVar(value="就绪")
        self.progress_var = tk.DoubleVar(value=0)
        self.udp_proxy_var = tk.StringVar(value="")
        self.timestamp_var = tk.BooleanVar(value=True)
        self.multi_quality_var = tk.BooleanVar(value=False)
        self.output_csv_var = tk.BooleanVar(value=False) 

        # 创建UI
        self.create_widgets()

        # 加载配置
        self.load_config()

    def create_widgets(self):
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # URL输入区域
        url_frame = ttk.LabelFrame(main_frame, text="JSON源", padding="5")
        url_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        ttk.Label(url_frame, text="URL:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.url_combo = ttk.Combobox(url_frame, textvariable=self.url_var, width=60)
        self.url_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.url_combo['values'] = (
            "http://183.235.11.39:8082/epg/api/custom/getAllChannel2.json",
            "http://183.235.16.92:8082/epg/api/custom/getAllChannel2.json",
            "http://192.168.1.201:8080/http://183.235.11.39:8082/epg/api/custom/getAllChannel2.json",
            "http://192.168.1.201/cgi-bin/iptv/epg/api/custom/getAllChannel2.json"
        )

        # 选项区域
        options_frame = ttk.LabelFrame(main_frame, text="选项", padding="5")
        options_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=5)

        # 流类型选择
        ttk.Label(options_frame, text="流类型:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.stream_var = tk.StringVar(value="ZTE")
        ttk.Radiobutton(options_frame, text="ZTE", variable=self.stream_var, value="ZTE").grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Radiobutton(options_frame, text="HW", variable=self.stream_var, value="HW").grid(row=0, column=2, sticky=tk.W, padx=5, pady=2)
        ttk.Radiobutton(options_frame, text="两者都尝试", variable=self.stream_var, value="两者都尝试").grid(row=0, column=3, sticky=tk.W, padx=5, pady=2)

        # 画质选择
        ttk.Label(options_frame, text="画质偏好:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.quality_var = tk.StringVar(value="高清优先")
        ttk.Radiobutton(options_frame, text="超高清优先", variable=self.quality_var, value="超高清优先").grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Radiobutton(options_frame, text="高清优先", variable=self.quality_var, value="高清优先").grid(row=1, column=2, sticky=tk.W, padx=5, pady=2)
        ttk.Radiobutton(options_frame, text="标清优先", variable=self.quality_var, value="标清优先").grid(row=1, column=3, sticky=tk.W, padx=5, pady=2)

        # 输出格式选择
        ttk.Label(options_frame, text="输出格式:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.output_format_var = tk.StringVar(value="M3U")
        ttk.Radiobutton(options_frame, text="M3U", variable=self.output_format_var, value="M3U").grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Radiobutton(options_frame, text="DIYP", variable=self.output_format_var, value="DIYP").grid(row=2, column=2, sticky=tk.W, padx=5, pady=2)
        
        # 输出选项
        ttk.Label(options_frame, text="输出选项:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        ttk.Checkbutton(options_frame, text="添加时间戳", variable=self.timestamp_var, command=self.toggle_timestamp).grid(row=3, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Checkbutton(options_frame, text="多画质", variable=self.multi_quality_var).grid(row=3, column=2, sticky=tk.W, padx=5, pady=2)
        ttk.Checkbutton(options_frame, text="输出中间表", variable=self.output_csv_var).grid(row=3, column=3, sticky=tk.W, padx=5, pady=2) 

        # 高级选项区域
        advanced_frame = ttk.LabelFrame(main_frame, text="高级选项", padding="5")
        advanced_frame.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5)

        # UDP代理设置
        ttk.Label(advanced_frame, text="UDP代理:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.udp_proxy_combo = ttk.Combobox(advanced_frame, textvariable=self.udp_proxy_var, width=20, state="combobox")
        self.udp_proxy_combo['values'] = (
            "",
            "192.168.1.1:4022",
            "192.168.1.199:4022",
            "192.168.1.201:4022"
        )
        self.udp_proxy_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5, pady=2)
        ttk.Label(advanced_frame, text="格式: ip:port").grid(row=0, column=2, sticky=tk.W, padx=5, pady=2)
        
        # 输出文件区域
        output_frame = ttk.LabelFrame(main_frame, text="输出文件", padding="5")
        output_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        ttk.Entry(output_frame, textvariable=self.output_var, width=60).grid(row=0, column=0, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.output_entry = ttk.Button(output_frame, text="浏览...", command=self.browse_output)
        self.output_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)

        # 进度条
        progress_frame = ttk.Frame(main_frame)
        progress_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        ttk.Progressbar(progress_frame, variable=self.progress_var, length=765).grid(row=0, column=0, sticky=(tk.W, tk.E), padx=5, pady=2)

        # 状态标签
        self.status_label = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=2)

        # 按钮区域
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, columnspan=2, pady=10)

        ttk.Button(button_frame, text="仅下载", command=self.start_download_only).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="下载并转换", command=self.start_download_and_convert).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="选择本地文件", command=self.select_local_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="清空", command=self.clear_all).pack(side=tk.LEFT, padx=5)

        # 日志区域
        log_frame = ttk.LabelFrame(main_frame, text="操作日志", padding="5")
        log_frame.grid(row=6, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, width=80)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 配置权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(6, weight=1)
        url_frame.columnconfigure(1, weight=1)
        output_frame.columnconfigure(1, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

    def generate_timestamp_filename(self, base_name="output"):
        """生成带时间戳的文件名"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{base_name}_{timestamp}"

    def toggle_timestamp(self):
        """切换时间戳选项时的处理"""
        output_format = self.output_format_var.get()
        ext = '.m3u' if output_format == 'M3U' else '.txt'  # 根据输出格式获取后缀
        if self.timestamp_var.get():
            # 如果启用时间戳，更新文件名
            current_path = self.output_var.get()
            if current_path:
                # 提取基础文件名（不含路径和时间戳）
                dir_name = os.path.dirname(current_path)
                base_name = os.path.basename(current_path)

                # 移除可能的旧扩展名
                if base_name.endswith('.m3u') or base_name.endswith('.txt'):
                    base_name = os.path.splitext(base_name)[0]

                # 移除可能的时间戳部分
                if '_' in base_name and base_name.split('_')[-1].isdigit() and len(base_name.split('_')[-1]) == 14:
                    base_name = '_'.join(base_name.split('_')[:-1])

                if not base_name or base_name == "output":
                    base_name = "iptv_playlist"

                new_filename = self.generate_timestamp_filename(base_name) + ext
                if dir_name:
                    new_filename = os.path.join(dir_name, new_filename)

                self.output_var.set(new_filename)
        else:
            # 如果禁用时间戳，移除时间戳
            current_path = self.output_var.get()
            if current_path:
                dir_name = os.path.dirname(current_path)
                base_name = os.path.basename(current_path)

                # 移除可能的旧扩展名
                if base_name.endswith('.m3u') or base_name.endswith('.txt'):
                    base_name = os.path.splitext(base_name)[0]

                # 检查是否有时间戳格式（YYYYMMDD_HHMMSS）
                if '_' in base_name:
                    parts = base_name.split('_')
                    if len(parts) > 1 and len(parts[-1]) == 14 and parts[-1].isdigit():
                        base_name = '_'.join(parts[:-1])

                if not base_name:
                    base_name = "output"

                new_filename = f"{base_name}{ext}"
                if dir_name:
                    new_filename = os.path.join(dir_name, new_filename)

                self.output_var.set(new_filename)

    def browse_output(self):
        """浏览选择输出文件"""
        # 获取当前文件名作为默认值
        current_file = self.output_var.get()
        if not current_file:
            if self.timestamp_var.get():
                current_file = self.generate_timestamp_filename()
            else:
                output_format = self.output_format_var.get()
                ext = '.m3u' if output_format == 'M3U' else '.txt'  # 根据输出格式获取后缀
                current_file = f"output{ext}"

        output_format = self.output_format_var.get()
        ext = '.m3u' if output_format == 'M3U' else '.txt'  # 根据输出格式获取后缀

        file_path = filedialog.asksaveasfilename(
            defaultextension=ext,
            initialfile=os.path.basename(current_file),
            filetypes=[("M3U Files", "*.m3u"), ("TXT Files", "*.txt"), ("All Files", "*.*")]
        )

        if file_path:
            # 如果用户选择了文件名但启用了时间戳，自动添加时间戳
            if self.timestamp_var.get():
                dir_name = os.path.dirname(file_path)
                base_name = os.path.basename(file_path)

                # 移除可能的旧扩展名
                if base_name.endswith('.m3u') or base_name.endswith('.txt'):
                    base_name = os.path.splitext(base_name)[0]

                # 生成带时间戳的文件名
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_filename = f"{base_name}_{timestamp}{ext}"
                file_path = os.path.join(dir_name, new_filename)

            self.output_var.set(file_path)

    def start_download_only(self):
        url = self.url_var.get()
        if not url:
            messagebox.showerror("错误", "请输入JSON源URL")
            return
        self.set_ui_enabled(False)
        self.status_var.set("开始下载JSON文件...")
        threading.Thread(target=self.download_thread_only, args=(url,), daemon=True).start()

    def download_thread_only(self, url):
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            temp_dir = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'temp')
            os.makedirs(temp_dir, exist_ok=True)
            file_name = f"downloaded_{timestamp}.json"
            file_path = os.path.join(temp_dir, file_name)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(response.text)
            self.log("\n    URL地址: "+url+"\n    文件保存为: " + file_path + "\n    下载完成")         
        except Exception as e:
            self.root.after(0, self.on_download_error, str(e))
        finally:
            self.root.after(0, self.set_ui_enabled, True)
            self.set_ui_enabled(True)
            self.status_var.set("完成")   

    def start_download_and_convert(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("警告", "请输入JSON文件的URL地址")
            return

        if not url.startswith(('http://', 'https://')):
            messagebox.showwarning("警告", "请输入有效的URL地址")
            return

        self.save_config()  # 保存当前参数
        self.log(f"开始下载: {url}")
        self.log("正在连接服务器...")
        self.set_ui_enabled(False)
        self.update_progress(0, "正在连接...")

        # 启动下载线程
        thread = threading.Thread(target=self.download_thread, args=(url,))
        thread.daemon = True
        thread.start()

    def download_thread(self, url):
        try:
            self.log(f"开始下载: {url}")

            # 使用会话处理可能的cookie和重定向
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })

            response = session.get(url, stream=True, timeout=30)
            response.raise_for_status()

            # 检查内容类型
            content_type = response.headers.get('content-type', '')
            if 'json' not in content_type and 'text' not in content_type:
                self.root.after(0, lambda: self.on_download_error(f"无效的内容类型: {content_type}"))
                return

            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(self.temp_json_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        # 更新进度（如果有总大小信息）
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            self.update_progress(progress, f"下载进度: {progress:.1f}%")
                        else:
                            # 如果没有总大小信息，显示已下载大小
                            self.update_progress(0, f"已下载: {downloaded / 1024:.1f} KB")

            # 验证下载的文件是否是有效的JSON
            try:
                with open(self.temp_json_file, 'r', encoding='utf-8') as f:
                    json.load(f)  # 尝试解析JSON
                self.root.after(0, lambda: self.on_download_finished(self.temp_json_file, True))
            except json.JSONDecodeError:
                self.root.after(0, lambda: self.on_download_error("下载的文件不是有效的JSON格式"))
            except Exception as e:
                self.root.after(0, lambda: self.on_download_error(f"文件验证失败: {str(e)}"))

        except requests.exceptions.Timeout:
            self.root.after(0, lambda: self.on_download_error("连接超时"))
        except requests.exceptions.ConnectionError:
            self.root.after(0, lambda: self.on_download_error("网络连接错误"))
        except requests.exceptions.HTTPError as e:
            self.root.after(0, lambda: self.on_download_error(f"HTTP错误: {e.response.status_code}"))
        except Exception as e:
            self.root.after(0, lambda: self.on_download_error(f"下载失败: {str(e)}"))

    def select_local_file(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")]
        )
        if file_path:
            self.save_config()  # 保存当前参数
            self.start_conversion(file_path)

    def start_conversion(self, json_file):
        """开始转换过程"""
        output_file = self.output_var.get().strip()
        if not output_file:
            output_format = self.output_format_var.get()
            ext = '.m3u' if output_format == 'M3U' else '.txt'  # 根据输出格式获取后缀
            output_file = f"output{ext}"

        # 若启用时间戳且文件名不含时间戳，则添加时间戳
        if self.timestamp_var.get():
            dir_name = os.path.dirname(output_file)
            base_name = os.path.basename(output_file)
            name_without_ext, old_ext = os.path.splitext(base_name)
            output_format = self.output_format_var.get()
            ext = '.m3u' if output_format == 'M3U' else '.txt'  # 根据输出格式获取后缀

            # 检查是否已经包含时间戳
            has_timestamp = False
            if '_' in name_without_ext:
                parts = name_without_ext.split('_')
                if len(parts) > 1 and len(parts[-1]) == 14 and parts[-1].isdigit():
                    has_timestamp = True

            if not has_timestamp:
                timestamped_name = self.generate_timestamp_filename(name_without_ext)
                output_file = os.path.join(dir_name, f"{timestamped_name}{ext}")

        # 确保输出目录存在
        output_dir = os.path.dirname(output_file)
        if output_dir and not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
                self.log(f"创建输出目录: {output_dir}")
            except Exception as e:
                self.log(f"创建目录失败: {str(e)}")
                messagebox.showerror("错误", f"无法创建输出目录: {str(e)}")
                self.set_ui_enabled(True)
                return

        # 获取其他参数并启动转换
        stream_type = self.stream_var.get()
        use_zte = stream_type in ["ZTE", "两者都尝试"]
        use_hw = stream_type in ["HW", "两者都尝试"]

        quality_str = self.quality_var.get()
        if quality_str == "高清优先":
            quality = "high"
        elif quality_str == "标清优先":
            quality = "standard"
        elif quality_str == "超高清优先":
            quality = "ultra_high"
        else:
            quality = "high"
        multi_quality = self.multi_quality_var.get()
        output_format = self.output_format_var.get()
        udp_proxy = self.udp_proxy_var.get().strip()
        output_csv = self.output_csv_var.get()  # 获取是否输出中间表的值

        self.log(f"开始转换: {json_file} -> {output_file}")
        self.log(f"参数: 流类型={stream_type}, 画质={quality}, 多画质={multi_quality}, 输出格式={output_format}, UDP代理={udp_proxy}, 输出中间表={output_csv}")

        # 启动转换线程
        thread = threading.Thread(
            target=self.conversion_thread,
            args=(json_file, output_file, use_zte, use_hw, quality, multi_quality, output_format, udp_proxy,output_csv)
        )
        thread.daemon = True
        thread.start()

    def conversion_thread(self, json_file, output_file, use_zte, use_hw, quality, multi_quality, output_format, udp_proxy,output_csv):
        try:
            converter = IPTV2M3U()

            # 首先检查文件是否存在且可读
            if not os.path.exists(json_file):
                self.root.after(0, lambda: self.on_conversion_error(f"文件不存在: {json_file}"))
                return

            # 读取文件内容进行调试
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    content = f.read(500)  # 只读取前500字符用于调试
                    print(f"文件内容预览: {content[:200]}...")
            except Exception as e:
                print(f"读取文件失败: {e}")

            # 加载JSON文件
            if not converter.load_json(json_file):
                self.root.after(0, lambda: self.on_conversion_error("加载JSON文件失败，请检查文件格式"))
                return

            total_channels = len(converter.channels)
            if total_channels == 0:
                self.root.after(0, lambda: self.on_conversion_error("JSON文件中没有找到频道数据"))
                return

            def progress_callback(current, total):
                progress = (current / total) * 100
                self.update_progress(progress, f"处理中: {current}/{total}")

            # 根据output_csv_var的值决定是否生成CSV中间数据文件
            if output_csv:
                # 先生成CSV中间数据文件
                csv_output_file = os.path.splitext(output_file)[0] + '_channels_output.csv'
                if self.timestamp_var.get():
                    # 如果启用了时间戳，创建带时间戳的CSV文件名
                    dir_name = os.path.dirname(csv_output_file)
                    base_name = os.path.basename(csv_output_file)
                    name_without_ext, _ = os.path.splitext(base_name)
                    # 检查name_without_ext是否已经包含时间戳
                    if '_' in name_without_ext:
                        parts = name_without_ext.split('_')
                        # 检查最后一部分是否是时间戳格式(14位数字)
                        if len(parts) > 1 and len(parts[-1]) == 14 and parts[-1].isdigit():
                            # 移除已存在的时间戳
                            name_without_ext = '_'.join(parts[:-1])
                    # 创建新的带时间戳的文件名
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    csv_output_file = os.path.join(dir_name, f"output_{timestamp}_channels_output.csv")

                self.log(f"开始生成CSV中间数据文件: {csv_output_file}")
                if not converter.generate_csv(csv_output_file, progress_callback):
                    self.root.after(0, lambda: self.on_conversion_error("生成CSV中间数据文件失败"))
                    return
                self.log(f"CSV中间数据文件生成完成: {csv_output_file}")
            else:
                self.log("跳过CSV中间数据文件生成")

            # 根据输出格式选择生成方法，并传递multi_quality参数
            if output_format == 'M3U':
                success = converter.generate_m3u(
                    output_file,
                    use_zte=use_zte,
                    use_hw=use_hw,
                    quality_preference=quality,
                    progress_callback=progress_callback,
                    udp_proxy=udp_proxy,
                    multi_quality=multi_quality
                )
            else:
                success = converter.generate_diyp(
                    output_file,
                    use_zte=use_zte,
                    use_hw=use_hw,
                    quality_preference=quality,
                    progress_callback=progress_callback,
                    udp_proxy=udp_proxy,
                    multi_quality=multi_quality
                )

            if success:
                # 检查生成的文件内容
                try:
                    with open(output_file, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        if len(lines) > 1:
                            self.root.after(0, lambda: self.on_conversion_finished(output_file, True))
                        else:
                            self.root.after(0, lambda: self.on_conversion_error("生成的文件为空，请检查JSON格式"))
                except Exception as e:
                    self.root.after(0, lambda: self.on_conversion_error(f"检查输出文件失败: {str(e)}"))
            else:
                self.root.after(0, lambda: self.on_conversion_error("转换失败，请查看控制台输出"))

        except Exception as e:
            error_msg = f"转换错误: {str(e)}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            self.root.after(0, lambda: self.on_conversion_error(error_msg))

    def update_progress(self, value, message):
        """线程安全的进度更新"""
        def update_ui():
            self.progress_var.set(value)
            self.status_var.set(message)
            # 强制更新界面
            self.root.update_idletasks()

        self.root.after(0, update_ui)

    def on_download_finished(self, file_path, success):
        if success:
            self.log("下载完成")
            self.start_conversion(file_path)
        else:
            self.log("下载失败")
            self.set_ui_enabled(True)

    def on_download_error(self, error_msg):
        self.log(error_msg)
        messagebox.showerror("错误", error_msg)
        self.set_ui_enabled(True)

    def on_conversion_finished(self, output_file, success):
        if success:
            # 读取生成的文件内容并显示统计信息
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    channel_count = len([line for line in lines if line.startswith(('#EXTINF', 'IPTV频道')) or line.strip().count(',') > 0])
                    self.log(f"转换完成: {output_file}")
                    self.log(f"共生成 {channel_count} 个频道")
                    messagebox.showinfo("成功", f"文件已生成: {output_file}\n共包含 {channel_count} 个频道")
            except Exception as e:
                self.log(f"读取输出文件失败: {str(e)}")
                messagebox.showinfo("成功", f"文件已生成: {output_file}")
        else:
            self.log("转换失败")

        self.set_ui_enabled(True)
        self.progress_var.set(0)

    def on_conversion_error(self, error_msg):
        self.log(error_msg)
        messagebox.showerror("错误", error_msg)
        self.set_ui_enabled(True)
        self.progress_var.set(0)

    def log(self, message):
        """线程安全的日志记录"""
        def add_log():
            self.log_text.insert(tk.END, f"[INFO] {message}\n")
            self.log_text.see(tk.END)
            # 确保日志及时显示
            self.log_text.update_idletasks()

        self.root.after(0, add_log)

    def set_ui_enabled(self, enabled):
        state = tk.NORMAL if enabled else tk.DISABLED
        self.url_combo.config(state=state)
        self.output_entry.config(state=state)

    def clear_all(self):
        """清空所有输入"""
        self.url_var.set("")
        self.udp_proxy_var.set("")  # 清空 UDP 代理输入
        # 清空时生成新的带时间戳的文件名
        if self.timestamp_var.get():
            output_format = self.output_format_var.get()
            ext = '.m3u' if output_format == 'M3U' else '.txt'
            self.output_var.set(self.generate_timestamp_filename()[:-4] + ext)
        else:
            output_format = self.output_format_var.get()
            ext = '.m3u' if output_format == 'M3U' else '.txt'
            self.output_var.set(f"output{ext}")
        self.log_text.delete(1.0, tk.END)
        self.status_var.set("就绪")
        self.progress_var.set(0)

    def on_closing(self):
        # 清理临时文件
        if os.path.exists(self.temp_json_file):
            try:
                os.remove(self.temp_json_file)
            except:
                pass
        self.root.destroy()

    def load_config(self):
        """加载配置"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 恢复各个设置
                    if 'url' in config:
                        self.url_var.set(config['url'])
                    if 'url_history' in config:
                        self.url_combo['values'] = config['url_history']
                    if 'output_file' in config:
                        self.output_var.set(config['output_file'])
                    if 'stream_type' in config:
                        self.stream_var.set(config['stream_type'])
                    if 'quality' in config:
                        self.quality_var.set(config['quality'])
                    if 'output_format' in config:
                        self.output_format_var.set(config['output_format'])
                    if 'udp_proxy' in config:
                        self.udp_proxy_var.set(config['udp_proxy'])
                    if 'timestamp' in config:
                        self.timestamp_var.set(config['timestamp'])
                    if 'multi_quality' in config:
                        self.multi_quality_var.set(config['multi_quality'])
                    if 'output_csv' in config:
                        self.output_csv_var.set(config['output_csv'])
        except Exception as e:
            print(f"加载配置失败: {e}")

    def save_config(self):
        """保存配置"""
        try:
            config = {
                'url': self.url_var.get(),
                'url_history': self.url_combo['values'],
                'output_file': self.output_var.get(),
                'stream_type': self.stream_var.get(),
                'quality': self.quality_var.get(),
                'output_format': self.output_format_var.get(),
                'udp_proxy': self.udp_proxy_var.get(),
                'timestamp': self.timestamp_var.get(),
                'multi_quality': self.multi_quality_var.get(),
                'output_csv': self.output_csv_var.get()
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"保存配置失败: {e}")


def main():
    root = tk.Tk()
    app = IPTV2M3UGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()

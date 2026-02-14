#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlitアプリ: 一条工務店CAD図面3D化アプリ

"""

# ichijo_coreのインストールチェックと自動インストール
import subprocess
import sys
import os

def install_ichijo_core():
    """Streamlit Cloud用: ローカルのichijo_core_checkまたはGitHubからichijo_coreをロード"""
    
    # **優先: ローカルのichijo_core_checkディレクトリを使用**
    # 現在のファイルの親ディレクトリにichijo_core_checkが存在するか確認
    current_dir = os.path.dirname(os.path.abspath(__file__))
    local_ichijo_path = os.path.join(current_dir, "ichijo_core_check")
    
    if os.path.exists(local_ichijo_path) and os.path.isdir(local_ichijo_path):
        # ローカルのichijo_core_checkをsys.pathに追加
        if local_ichijo_path not in sys.path:
            sys.path.insert(0, local_ichijo_path)
        
        try:
            import ichijo_core
            # ローカル版のインポート成功
            return True, None
        except Exception as e:
            # ローカル版のインポート失敗 → GitHubからインストールを試みる
            pass
    
    # **フォールバック: GitHubからインストール**
    # 既存のインポートチェック（バージョン確認）
    try:
        import ichijo_core
        
        # バージョンが期待値と一致するかチェック（0.0.13系を許可）
        if ichijo_core.__version__.startswith("0.0.13"):
            return True, None
        else:
            # 強制的に再インストール
            pass
    except Exception as e:
        pass
    
    # GitHubからインストール
    try:
        import streamlit as st_temp
        
        if not hasattr(st_temp, 'secrets') or 'GITHUB_TOKEN' not in st_temp.secrets:
            error_msg = "GITHUB_TOKEN not found in Streamlit secrets"
            return False, error_msg
        
        token = st_temp.secrets['GITHUB_TOKEN']
        
        # インストール用の一時ディレクトリ
        import tempfile
        target_dir = tempfile.mkdtemp(prefix="ichijo_core_")
        
        if target_dir not in sys.path:
            sys.path.insert(0, target_dir)
        
        # 最新コミット（aaed720: 階段パターン生成関数をstair_utilsに移行）を指定
        commit_hash = "aaed720"
        install_url = f"git+https://{token}@github.com/curtinex/ichijo_core.git@{commit_hash}"
        
        # アンインストール
        subprocess.run(
            [sys.executable, "-m", "pip", "uninstall", "-y", "ichijo_core"],
            capture_output=True,
            text=True
        )
        
        # インストール
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--target", target_dir, "--force-reinstall", "--no-cache-dir", install_url],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0:
            # インポートキャッシュをクリア
            import importlib
            importlib.invalidate_caches()
            
            # インポート確認
            import ichijo_core
            return True, None
        else:
            error_msg = f"Installation failed: {result.stderr[:500]}"
            return False, error_msg
            
    except Exception as e:
        error_msg = f"Error: {type(e).__name__}: {str(e)}"
        return False, error_msg

# アプリ起動時に一度だけインストール
success, error_detail = install_ichijo_core()
if not success:
    import streamlit as st
    st.error("❌ ichijo_core のロードに失敗しました")
    if error_detail:
        with st.expander("🔍 エラー詳細を表示"):
            st.code(error_detail)
    st.info("""
    **トラブルシューティング:**
    
    1. Streamlit Cloud の **Settings → Secrets** で `GITHUB_TOKEN` が正しく設定されているか確認
    2. トークンの形式: `GITHUB_TOKEN = "ghp_xxxxxxxxxxxx"`
    3. トークンの権限: Contents (Read-only), ichijo_core リポジトリへのアクセス権
    4. アプリを再起動してみてください
    """)
    st.stop()

import io
import re
import time
import json
import math
from pathlib import Path
from datetime import datetime
import zipfile

import numpy as np
import streamlit as st
import fitz  # PyMuPDF (for page count)
from streamlit_image_coordinates import streamlit_image_coordinates
from PIL import Image

# ichijo_core から全モジュールをインポート（必須）
try:
    from ichijo_core.pdf_to_image import pdf_to_image
    from ichijo_core.refine_from_image import refine_floor_plan_from_image
    from ichijo_core.extract_walls_to_3d_v2 import process_image_to_3d
    from ichijo_core.visualize_3d_walls import visualize_3d_walls
    from ichijo_core.auto_merge_walls import WallAutoMerger
    from ichijo_core.geometry_utils import (
        calc_distance as _calc_distance,
        calc_angle_diff as _calc_angle_diff,
        wall_angle_deg as _wall_angle_deg,
        angle_diff_deg as _angle_diff_deg,
        determine_line_direction as _determine_line_direction,
    )
    from ichijo_core.furniture_utils import (
        FURNITURE_HEIGHT_OPTIONS,
        FURNITURE_COLOR_OPTIONS,
    )
    from ichijo_core.stair_utils import (
        STAIR_PATTERNS,
    )
    from ichijo_core.ui_helpers import (
        prepare_display_from_pil as _prepare_display_from_pil,
        prepare_display_from_bytes as _prepare_display_from_bytes,
        display_to_original as _display_to_original,
        display_to_meter as _display_to_meter,
        save_uploaded_file as _save_uploaded_file,
        generate_3d_viewer_html as _generate_3d_viewer_html,
    )
    
    # window_utilsとwall_editingのインポート（ichijo_coreは使わずフォールバック版のみ使用）
    try:
        # ichijo_coreがあってもフォールバック版を使う（ID生成の修正を確実に適用）
        raise ImportError("Force use of fallback functions")
    except ImportError as e:
        # フォールバック関数を定義
        import copy
        def add_window_walls(json_data, wall1, wall2, window_height, base_height, room_height, window_model=None, window_height_mm=None):
            """窓で分断された2本の壁の間に、床側と天井側の壁を追加（フォールバック版）"""
            updated_data = copy.deepcopy(json_data)
            walls = updated_data['walls']
            endpoints = [
                (wall1['start'], wall2['start']),
                (wall1['start'], wall2['end']),
                (wall1['end'], wall2['start']),
                (wall1['end'], wall2['end']),
            ]
            min_dist = float('inf')
            window_start = None
            window_end = None
            for p1, p2 in endpoints:
                dist = math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)
                if dist < min_dist:
                    min_dist = dist
                    window_start = p1
                    window_end = p2
            thicknesses = [w.get('thickness', 0.12) for w in walls if 'thickness' in w]
            default_thickness = sum(thicknesses) / len(thicknesses) if thicknesses else 0.12
            
            # 既存のIDを全て取得して、最大値を確実に取得（重複回避）
            existing_ids = []
            for w in walls:
                try:
                    existing_ids.append(int(w['id']))
                except (ValueError, TypeError):
                    pass
            max_id = max(existing_ids) if existing_ids else 0
            
            added_walls = []
            floor_wall = {
                'id': max_id + 1,
                'start': [round(window_start[0], 3), round(window_start[1], 3)],
                'end': [round(window_end[0], 3), round(window_end[1], 3)],
                'height': round(base_height, 3),
                'base_height': 0.0,
                'length': round(min_dist, 3),
                'thickness': round(default_thickness, 3),
                'source': 'window_added',
                'window_model': window_model,
                'window_height_mm': window_height_mm,
                'window_base_m': round(base_height, 3),
                'window_base_mm': int(round(base_height * 1000))
            }
            walls.append(floor_wall)
            added_walls.append(floor_wall)
            ceiling_height = room_height - (base_height + window_height)
            ceiling_wall = {
                'id': max_id + 2,
                'start': [round(window_start[0], 3), round(window_start[1], 3)],
                'end': [round(window_end[0], 3), round(window_end[1], 3)],
                'height': round(ceiling_height, 3),
                'base_height': round(base_height + window_height, 3),
                'length': round(min_dist, 3),
                'thickness': round(default_thickness, 3),
                'source': 'window_added',
                'window_model': window_model,
                'window_height_mm': window_height_mm,
                'window_base_m': round(base_height + window_height, 3),
                'window_base_mm': int(round((base_height + window_height) * 1000))
            }
            walls.append(ceiling_wall)
            added_walls.append(ceiling_wall)
            updated_data['metadata']['total_walls'] = len(walls)
            return updated_data, added_walls
        
        def find_closest_wall_to_point(walls, point_px, scale, margin, img_height, min_x, min_y, max_x, max_y):
            """ポイントから最も近い壁を見つける（フォールバック版）"""
            min_distance = float('inf')
            closest_wall = None
            point_m = [
                (point_px[0] - margin) / scale + min_x,
                (img_height - point_px[1] - margin) / scale + min_y
            ]
            for wall in walls:
                try:
                    start = wall.get('start')
                    end = wall.get('end')
                    if not isinstance(start, (list, tuple)) or not isinstance(end, (list, tuple)):
                        continue
                    if len(start) < 2 or len(end) < 2:
                        continue
                    x1, y1 = float(start[0]), float(start[1])
                    x2, y2 = float(end[0]), float(end[1])
                except (TypeError, ValueError, KeyError):
                    continue
                dx = x2 - x1
                dy = y2 - y1
                if dx == 0 and dy == 0:
                    distance = math.sqrt((point_m[0] - x1)**2 + (point_m[1] - y1)**2)
                else:
                    t = max(0, min(1, ((point_m[0] - x1) * dx + (point_m[1] - y1) * dy) / (dx**2 + dy**2)))
                    closest_x = x1 + t * dx
                    closest_y = y1 + t * dy
                    distance = math.sqrt((point_m[0] - closest_x)**2 + (point_m[1] - closest_y)**2)
                if distance < min_distance:
                    min_distance = distance
                    closest_wall = wall
            return closest_wall, min_distance
        
        # wall_editing関数のフォールバック（7つの関数）
        def _point_to_line_segment_distance(px, py, x1, y1, x2, y2):
            """点から線分までの最短距離を計算（フォールバック版）"""
            dx = x2 - x1
            dy = y2 - y1
            len_sq = dx * dx + dy * dy
            if len_sq == 0:
                return math.sqrt((px - x1)**2 + (py - y1)**2)
            t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / len_sq))
            nearest_x = x1 + t * dx
            nearest_y = y1 + t * dy
            return math.sqrt((px - nearest_x)**2 + (py - nearest_y)**2)
        
        def _find_nearest_wall_from_click(click_x, click_y, walls, scale, margin, img_height, min_x, min_y, max_x, max_y, threshold=20):
            """クリック位置から最も近い壁を検出（フォールバック版）
            同じ座標の壁が複数ある場合は最初に見つかった壁のみを返す（窓の壁の重複選択を防ぐ）
            """
            min_distance = float('inf')
            nearest_wall = None
            for wall in walls:
                start_m = wall['start']
                end_m = wall['end']
                start_px_x = int((start_m[0] - min_x) * scale) + margin
                start_px_y = img_height - (int((start_m[1] - min_y) * scale) + margin)
                end_px_x = int((end_m[0] - min_x) * scale) + margin
                end_px_y = img_height - (int((end_m[1] - min_y) * scale) + margin)
                distance = _point_to_line_segment_distance(click_x, click_y, start_px_x, start_px_y, end_px_x, end_px_y)
                if distance < min_distance:
                    min_distance = distance
                    nearest_wall = wall
            if min_distance <= threshold:
                return nearest_wall, min_distance
            else:
                return None, None
        
        def _select_best_wall_pair_from_4(walls):
            """4本の壁から結合すべき最適な2本を選択（フォールバック版）"""
            if len(walls) < 2:
                return None
            vertical_walls = []
            horizontal_walls = []
            for wall in walls:
                x1, y1 = wall['start']
                x2, y2 = wall['end']
                dx = abs(x2 - x1)
                dy = abs(y2 - y1)
                if dx < dy:
                    vertical_walls.append(wall)
                else:
                    horizontal_walls.append(wall)
            dX = float('inf')
            if len(vertical_walls) >= 2:
                wall1 = vertical_walls[0]
                wall2 = vertical_walls[1]
                avg_x1 = (wall1['start'][0] + wall1['end'][0]) / 2
                avg_x2 = (wall2['start'][0] + wall2['end'][0]) / 2
                dX = abs(avg_x1 - avg_x2)
            dY = float('inf')
            if len(horizontal_walls) >= 2:
                wall1 = horizontal_walls[0]
                wall2 = horizontal_walls[1]
                avg_y1 = (wall1['start'][1] + wall1['end'][1]) / 2
                avg_y2 = (wall2['start'][1] + wall2['end'][1]) / 2
                dY = abs(avg_y1 - avg_y2)
            if dX == float('inf') and dY == float('inf'):
                return None
            if dX < dY:
                return vertical_walls[:2] if len(vertical_walls) >= 2 else None
            else:
                return horizontal_walls[:2] if len(horizontal_walls) >= 2 else None
        
        def _find_collinear_chains(walls_in_selection, distance_threshold=0.3, angle_threshold=15):
            """一直線上に並んだ連結壁線のチェーンを検出（フォールバック版）"""
            if len(walls_in_selection) < 2:
                return []
            connections = {}
            for i, wall1 in enumerate(walls_in_selection):
                wall1_id = wall1['id']
                if wall1_id not in connections:
                    connections[wall1_id] = []
                for j, wall2 in enumerate(walls_in_selection):
                    if i >= j:
                        continue
                    wall2_id = wall2['id']
                    if wall2_id not in connections:
                        connections[wall2_id] = []
                    angle_diff = _calc_angle_diff(wall1, wall2)
                    if angle_diff >= angle_threshold:
                        continue
                    endpoint_pairs = [
                        (wall1['end'], wall2['start'], 'end-start'),
                        (wall1['end'], wall2['end'], 'end-end'),
                        (wall1['start'], wall2['start'], 'start-start'),
                        (wall1['start'], wall2['end'], 'start-end'),
                    ]
                    for p1, p2, connection_type in endpoint_pairs:
                        distance = _calc_distance(p1, p2)
                        if distance < distance_threshold:
                            connections[wall1_id].append((wall2_id, connection_type, distance))
                            reverse_type = connection_type.split('-')[::-1]
                            reverse_type = f"{reverse_type[0]}-{reverse_type[1]}"
                            connections[wall2_id].append((wall1_id, reverse_type, distance))
                            break
            visited = set()
            chains = []
            def build_chain(start_wall_id, current_chain, visited_in_chain):
                if start_wall_id in visited_in_chain:
                    return
                visited_in_chain.add(start_wall_id)
                current_chain.append(start_wall_id)
                if start_wall_id in connections:
                    for connected_id, conn_type, dist in connections[start_wall_id]:
                        if connected_id not in visited_in_chain:
                            build_chain(connected_id, current_chain, visited_in_chain)
            for wall in walls_in_selection:
                wall_id = wall['id']
                if wall_id not in visited:
                    chain = []
                    visited_in_chain = set()
                    build_chain(wall_id, chain, visited_in_chain)
                    if len(chain) >= 2:
                        visited.update(chain)
                        chain_walls = [w for w in walls_in_selection if w['id'] in chain]
                        chains.append(chain_walls)
            return chains
        
        def _find_mergeable_walls(walls_in_selection, distance_threshold=0.3, angle_threshold=15):
            """選択範囲内で結合可能な壁線ペアまたはチェーンを探す（フォールバック版）"""
            candidates = []
            chains = _find_collinear_chains(walls_in_selection, distance_threshold, angle_threshold)
            for chain in chains:
                if len(chain) >= 2:
                    first_wall = chain[0]
                    last_wall = chain[-1]
                    all_endpoints = [first_wall['start'], first_wall['end'], last_wall['start'], last_wall['end']]
                    max_dist = 0
                    chain_start = None
                    chain_end = None
                    for i, p1 in enumerate(all_endpoints):
                        for j, p2 in enumerate(all_endpoints):
                            if i >= j:
                                continue
                            dist = _calc_distance(p1, p2)
                            if dist > max_dist:
                                max_dist = dist
                                chain_start = p1
                                chain_end = p2
                    total_angle_diff = 0
                    for i in range(len(chain) - 1):
                        total_angle_diff += _calc_angle_diff(chain[i], chain[i+1])
                    avg_angle_diff = total_angle_diff / (len(chain) - 1) if len(chain) > 1 else 0
                    candidates.append({
                        'walls': chain,
                        'is_chain': True,
                        'chain_length': len(chain),
                        'distance': max_dist,
                        'angle_diff': avg_angle_diff,
                        'new_start': chain_start,
                        'new_end': chain_end,
                        'confidence': 1.0
                    })
            for i, wall1 in enumerate(walls_in_selection):
                for j, wall2 in enumerate(walls_in_selection):
                    if i >= j:
                        continue
                    connections = [
                        (wall1['end'], wall2['start'], 'end-start', wall1['end'], wall2['end']),
                        (wall1['end'], wall2['end'], 'end-end', wall1['end'], wall2['start']),
                        (wall1['start'], wall2['start'], 'start-start', wall1['end'], wall2['end']),
                        (wall1['start'], wall2['end'], 'start-end', wall1['end'], wall2['start']),
                    ]
                    for p1, p2, connection_type, new_p1, new_p2 in connections:
                        distance = _calc_distance(p1, p2)
                        angle_diff = _calc_angle_diff(wall1, wall2)
                        if distance < distance_threshold and angle_diff < angle_threshold:
                            candidates.append({
                                'wall1': wall1,
                                'wall2': wall2,
                                'is_chain': False,
                                'distance': distance,
                                'angle_diff': angle_diff,
                                'connection': connection_type,
                                'new_start': new_p1,
                                'new_end': new_p2,
                                'confidence': 1.0 - (distance / distance_threshold)
                            })
            candidates.sort(key=lambda x: x['confidence'], reverse=True)
            return candidates
        
        def _merge_walls_in_json(json_data, merge_pairs):
            """JSONデータ内の壁線を結合（フォールバック版）"""
            updated_data = copy.deepcopy(json_data)
            walls = updated_data['walls']
            for pair in merge_pairs:
                if pair.get('is_chain', False) and 'walls' in pair:
                    chain_walls = pair['walls']
                    if len(chain_walls) < 2:
                        continue
                    first_wall_id = chain_walls[0]['id']
                    other_wall_ids = [w['id'] for w in chain_walls[1:]]
                    for wall in walls:
                        if wall['id'] == first_wall_id:
                            wall['start'] = pair['new_start']
                            wall['end'] = pair['new_end']
                            dx = wall['end'][0] - wall['start'][0]
                            dy = wall['end'][1] - wall['start'][1]
                            wall['length'] = round(math.sqrt(dx**2 + dy**2), 3)
                            break
                    walls[:] = [w for w in walls if w['id'] not in other_wall_ids]
                elif 'wall1' in pair and 'wall2' in pair:
                    wall1_id = pair['wall1']['id']
                    wall2_id = pair['wall2']['id']
                    conn = pair.get('connection')
                    w1 = pair['wall1']
                    w2 = pair['wall2']
                    if conn == 'end-start':
                        new_start = w1.get('start')
                        new_end = w2.get('end')
                    elif conn == 'end-end':
                        new_start = w1.get('start')
                        new_end = w2.get('start')
                    elif conn == 'start-start':
                        new_start = w1.get('end')
                        new_end = w2.get('end')
                    elif conn == 'start-end':
                        new_start = w1.get('end')
                        new_end = w2.get('start')
                    else:
                        new_start = pair.get('new_start')
                        new_end = pair.get('new_end')
                    for wall in walls:
                        if wall['id'] == wall1_id:
                            if new_start is not None:
                                wall['start'] = new_start
                            if new_end is not None:
                                wall['end'] = new_end
                            dx = wall['end'][0] - wall['start'][0]
                            dy = wall['end'][1] - wall['start'][1]
                            wall['length'] = round(math.sqrt(dx**2 + dy**2), 3)
                            break
                    walls[:] = [w for w in walls if w['id'] != wall2_id]
            updated_data['metadata']['total_walls'] = len(walls)
            return updated_data
        
        def _delete_walls_in_json(json_data, wall_ids_to_delete):
            """JSONデータ内の指定された壁線を削除（フォールバック版）"""
            updated_data = copy.deepcopy(json_data)
            walls = updated_data['walls']
            delete_ids = set(wall_ids_to_delete)
            walls[:] = [w for w in walls if w['id'] not in delete_ids]
            updated_data['metadata']['total_walls'] = len(walls)
            return updated_data
    
    # 関数の戻り値を検証（古いバージョンがロードされていないか確認）
    import io
    test_img = Image.new('RGB', (100, 100))
    test_result = _prepare_display_from_pil(test_img, max_width=50)
    if len(test_result) != 4:
        # 古いバージョンがロードされている場合、フォールバック関数を定義
        print(f"⚠️ Warning: ichijo_core.ui_helpers.prepare_display_from_pil returns {len(test_result)} values instead of 4. Using fallback.")
        
        def _prepare_display_from_pil_fallback(pil_img, max_width=800):
            orig_w, orig_h = pil_img.size
            target_w = max_width if orig_w > max_width else orig_w
            scale = target_w / orig_w
            target_h = int(orig_h * scale)
            display_img = pil_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
            return display_img, scale, orig_w, orig_h
        
        def _prepare_display_from_bytes_fallback(image_bytes, max_width=800):
            img = Image.open(io.BytesIO(image_bytes))
            return _prepare_display_from_pil_fallback(img, max_width=max_width)
        
        def _display_to_original_fallback(display_x, display_y, display_scale):
            return int(display_x / display_scale), int(display_y / display_scale)
        
        def _display_to_meter_fallback(display_x, display_y, display_scale, orig_img_height, margin, scale_px, min_x, min_y):
            orig_x, orig_y = _display_to_original_fallback(display_x, display_y, display_scale)
            meter_x = (orig_x - margin) / scale_px + min_x
            meter_y = (orig_img_height - orig_y - margin) / scale_px + min_y
            return meter_x, meter_y, orig_x, orig_y
        
        # フォールバック関数に置き換え
        _prepare_display_from_pil = _prepare_display_from_pil_fallback
        _prepare_display_from_bytes = _prepare_display_from_bytes_fallback
        _display_to_original = _display_to_original_fallback
        _display_to_meter = _display_to_meter_fallback
except ImportError as e:
    st.error(f"❌ ichijo_core パッケージが見つかりません: {e}")
    st.info("このアプリケーションを実行するには ichijo_core パッケージが必要です。")
    st.stop()

BASE_DIR = Path(__file__).parent
OUTPUTS_DIR = BASE_DIR / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True)

# 窓カタログ（外部ファイルがあれば読み込む。なければ組み込みのデフォルトを使用）
WINDOW_CATALOG_PATH = BASE_DIR / "window_catalog.json"
try:
    if WINDOW_CATALOG_PATH.exists():
        with open(WINDOW_CATALOG_PATH, 'r', encoding='utf-8') as f:
            WINDOW_CATALOG = json.load(f)
    else:
        # デフォルトカタログ（簡易）
        WINDOW_CATALOG = {
            "JF2020/JK2020": {"height": 603, "base": 1541},
            "JF2030/JK2030": {"height": 906, "base": 1238},
            "JF2042/JK2042": {"height": 1175, "base": 969}
        }
except Exception:
    WINDOW_CATALOG = {
        "JF2020/JK2020": {"height": 603, "base": 1541},
        "JF2030/JK2030": {"height": 906, "base": 1238},
        "JF2042/JK2042": {"height": 1175, "base": 969}
    }


def _reset_selection_state():
    """選択状態を完全にリセットする統一関数
    
    線を結合、窓を追加、線を削除などの実行後に呼び出して、
    選択状態を完全にクリアし、次の操作に備える。
    """
    st.session_state.skip_click_processing = True        # クリック処理をスキップ（再選択を防ぐ）
    st.session_state.rect_coords = []                    # 現在選択中の2点をクリア
    st.session_state.rect_coords_list = []               # 確定済み選択範囲リストをクリア
    st.session_state.reset_flag = True                   # リセットフラグを設定
    st.session_state.last_click = None                   # 最後のクリック位置をクリア
    st.session_state.merge_result = None                 # 結合結果をクリア
    st.session_state.selected_walls_for_merge = []       # 線を結合モードの壁選択をクリア
    st.session_state.selected_walls_for_window = []      # 窓追加モードの壁選択をクリア
    st.session_state.selected_walls_for_delete = []      # 線削除モードの壁選択をクリア
    
    # リセットカウンターをインクリメント（画像コンポーネントのキーをリセットするため）
    if 'selection_reset_counter' not in st.session_state:
        st.session_state.selection_reset_counter = 0
    st.session_state.selection_reset_counter += 1
    
    # 処理用の一時データをクリア
    if 'merge_walls_to_process' in st.session_state:
        del st.session_state.merge_walls_to_process
    if 'window_walls_to_process' in st.session_state:
        del st.session_state.window_walls_to_process
    if 'window_execution_params' in st.session_state:
        del st.session_state.window_execution_params
    if 'window_click_params' in st.session_state:
        del st.session_state.window_click_params
    # window_click_params_listは削除しない（ユーザーが設定した窓パラメータを保持）
    # if 'window_click_params_list' in st.session_state:
    #     del st.session_state.window_click_params_list
    if 'window_click_params_list_to_process' in st.session_state:
        del st.session_state.window_click_params_list_to_process


# 以下の関数は ichijo_core.geometry_utils からインポート済み:
# - _calc_distance, _calc_angle_diff, _wall_angle_deg, _angle_diff_deg, _determine_line_direction

# 以下の定数は ichijo_core.furniture_utils からインポート済み:
# - FURNITURE_HEIGHT_OPTIONS, FURNITURE_COLOR_OPTIONS


def _snap_to_grid(rect_pixel, json_data, scale, grid_size=0.45):
    """
    ピクセル座標の四角形をメートル座標に変換（グリッドスナップなし）
    
    Args:
        rect_pixel: (x1, y1, x2, y2) ピクセル座標の四角形
        json_data: JSON壁データ（座標変換用）
        scale: 可視化スケール (px/m)
        grid_size: グリッド間隔（m）※未使用
    
    Returns:
        (x_start_m, y_start_m, width_m, depth_m): メートル座標での配置情報
    """
    x1_px, y1_px, x2_px, y2_px = rect_pixel
    
    # 座標変換パラメータを取得
    all_x = [w['start'][0] for w in json_data['walls']] + [w['end'][0] for w in json_data['walls']]
    all_y = [w['start'][1] for w in json_data['walls']] + [w['end'][1] for w in json_data['walls']]
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    
    margin = 50
    img_height = int((max_y - min_y) * scale) + 2 * margin
    
    # ピクセル → メートル座標に変換（スナップなし、四角形範囲をそのまま使用）
    x1_m = (min(x1_px, x2_px) - margin) / scale + min_x
    y1_m = (img_height - max(y1_px, y2_px) - margin) / scale + min_y
    x2_m = (max(x1_px, x2_px) - margin) / scale + min_x
    y2_m = (img_height - min(y1_px, y2_px) - margin) / scale + min_y
    
    # 幅と奥行きを計算（選択範囲そのまま）
    width_m = x2_m - x1_m
    depth_m = y2_m - y1_m
    
    return x1_m, y1_m, width_m, depth_m


def _add_furniture_to_json(json_data, height_m, color_name, x_start, y_start, width, depth):
    """
    JSONに家具オブジェクトを追加
    
    Args:
        json_data: 既存のJSON
        height_m: 家具の高さ（メートル）
        color_name: 色の名前（FURNITURE_COLOR_OPTIONSのキー）
        x_start, y_start: 配置開始座標（メートル）
        width, depth: 幅と奥行き（メートル）
    """
    import copy
    
    updated_data = copy.deepcopy(json_data)
    
    # furnitureキーがなければ作成
    if 'furniture' not in updated_data:
        updated_data['furniture'] = []
    
    color_info = FURNITURE_COLOR_OPTIONS[color_name]
    
    # 家具オブジェクトを追加
    furniture_obj = {
        "type": f"家具（{color_name}）",
        "position": [x_start + width/2, y_start + depth/2],  # 中心座標
        "dimensions": {
            "width": width,
            "depth": depth,
            "height": height_m
        },
        "bounds": {
            "x_start": x_start,
            "y_start": y_start,
            "x_end": x_start + width,
            "y_end": y_start + depth
        },
        "color": color_name,
        "color_rgb": color_info["rgb"],
        "color_three_js": color_info["three_js"],
        "description": f"{color_name}の家具（高さ{height_m*100:.0f}cm）"
    }
    
    updated_data['furniture'].append(furniture_obj)
    
    # メタデータ更新
    if 'metadata' not in updated_data:
        updated_data['metadata'] = {}
    updated_data['metadata']['furniture_count'] = len(updated_data['furniture'])
    
    return updated_data


def _add_line_to_json(json_data, p1, p2, wall_height=None, scale=50):
    """四角形選択から線を追加（2点から自動判定した方向で線を生成）"""
    import copy
    
    # 元データを保護するためディープコピー
    updated_data = copy.deepcopy(json_data)
    walls = updated_data['walls']
    
    # 既存の壁から平均厚さを取得
    thicknesses = [w.get('thickness', 0.12) for w in walls if 'thickness' in w]
    default_thickness = sum(thicknesses) / len(thicknesses) if thicknesses else 0.12
    
    # 既存の壁から平均高さを取得（指定がない場合）
    if wall_height is None:
        heights = [w.get('height', 2.4) for w in walls if 'height' in w]
        wall_height = sum(heights) / len(heights) if heights else 2.4
    
    # 四角形の座標を計算
    x1, y1 = min(p1[0], p2[0]), min(p1[1], p2[1])
    x2, y2 = max(p1[0], p2[0]), max(p1[1], p2[1])
    
    # 可視化画像のメートル座標変換パラメータを取得
    all_x = [w['start'][0] for w in json_data['walls']] + [w['end'][0] for w in json_data['walls']]
    all_y = [w['start'][1] for w in json_data['walls']] + [w['end'][1] for w in json_data['walls']]
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    
    margin = 50
    img_height = int((max_y - min_y) * scale) + 2 * margin
    
    # ピクセル座標 → メートル座標に変換
    x1_m = (x1 - margin) / scale + min_x
    y1_m = (img_height - y1 - margin) / scale + min_y
    x2_m = (x2 - margin) / scale + min_x
    y2_m = (img_height - y2 - margin) / scale + min_y
    
    # 方向を判定
    direction = _determine_line_direction(p1, p2)
    
    # 新しい壁線を生成
    if direction == "vertical":
        # 縦線：x座標を四角形の中央に固定、y座標は上下端
        x_center = (x1_m + x2_m) / 2
        start_pt = [x_center, min(y1_m, y2_m)]
        end_pt = [x_center, max(y1_m, y2_m)]
    else:  # horizontal
        # 横線：y座標を四角形の中央に固定、x座標は左右端
        y_center = (y1_m + y2_m) / 2
        start_pt = [min(x1_m, x2_m), y_center]
        end_pt = [max(x1_m, x2_m), y_center]
    
    # 線の長さを計算
    dx = end_pt[0] - start_pt[0]
    dy = end_pt[1] - start_pt[1]
    length = round(math.sqrt(dx**2 + dy**2), 3)
    
    # 新しい壁のIDを生成（IDが文字列の場合も対応、重複回避）
    existing_ids = []
    for w in walls:
        try:
            existing_ids.append(int(w['id']))
        except (ValueError, TypeError):
            pass
    max_id = max(existing_ids) if existing_ids else 0
    new_id = max_id + 1
    
    # 新しい壁オブジェクトを作成（既存の壁と同じ構造）
    new_wall = {
        'id': new_id,
        'start': [round(start_pt[0], 3), round(start_pt[1], 3)],
        'end': [round(end_pt[0], 3), round(end_pt[1], 3)],
        'height': round(wall_height, 3),  # 既存の壁と同じ高さ
        'base_height': 0.0,  # 通常の壁は床から
        'length': length,
        'thickness': round(default_thickness, 3),  # 既存の壁と同じ厚さ
        'source': 'added'  # 手動追加の壁として記録
    }
    
    # 壁を追加
    walls.append(new_wall)
    
    # メタデータ更新
    updated_data['metadata']['total_walls'] = len(walls)
    
    return updated_data, direction, new_wall


def _point_in_rect(point, rect):
    """点が四角形内にあるかチェック（可視化画像のピクセル座標）"""
    x, y = point
    x_min, y_min = rect['left'], rect['top']
    x_max, y_max = rect['left'] + rect['width'], rect['top'] + rect['height']
    return x_min <= x <= x_max and y_min <= y <= y_max


def _line_intersects_rect(x1, y1, x2, y2, rect, tolerance=20):
    """線分が四角形と交差または近接しているかチェック（拡張版）"""
    x_min = rect['left'] - tolerance
    y_min = rect['top'] - tolerance
    x_max = rect['left'] + rect['width'] + tolerance
    y_max = rect['top'] + rect['height'] + tolerance
    
    # 1. 端点が四角形内にある
    if (x_min <= x1 <= x_max and y_min <= y1 <= y_max) or \
       (x_min <= x2 <= x_max and y_min <= y2 <= y_max):
        return True
    
    # 2. 線分が四角形の辺と交差するか（簡易判定）
    # 線分が四角形を完全に横断している場合
    if (x1 < x_min and x2 > x_max) or (x2 < x_min and x1 > x_max) or \
       (y1 < y_min and y2 > y_max) or (y2 < y_min and y1 > y_max):
        return True
    
    # 3. 四角形が線分の間にある
    if (min(x1, x2) <= x_max and max(x1, x2) >= x_min) and \
       (min(y1, y2) <= y_max and max(y1, y2) >= y_min):
        return True
    
    return False


def _wall_in_rect(wall, rect, scale, margin, img_height, min_x, min_y, max_x, max_y):
    """壁線が四角形選択範囲内または近接しているかチェック（拡張版）"""
    # 壁線のメートル座標をピクセル座標に変換（visualize_3d_wallsと同じロジック）
    x1_px = int((wall['start'][0] - min_x) * scale) + margin
    y1_px = img_height - (int((wall['start'][1] - min_y) * scale) + margin)
    x2_px = int((wall['end'][0] - min_x) * scale) + margin
    y2_px = img_height - (int((wall['end'][1] - min_y) * scale) + margin)
    
    # 線分が四角形と交差または近接しているかチェック（許容範囲20ピクセル）
    return _line_intersects_rect(x1_px, y1_px, x2_px, y2_px, rect, tolerance=20)


def _filter_walls_strictly_in_rect(walls, rect, scale, margin, img_height, min_x, min_y, max_x, max_y):
    """
    四角形範囲内に完全に含まれる壁線のみを返す（精密フィルタリング）
    交差や近接ではなく、両端点が四角形内にある線のみを抽出
    """
    filtered_walls = []
    
    x_rect_min = rect['left']
    x_rect_max = rect['left'] + rect['width']
    y_rect_min = rect['top']
    y_rect_max = rect['top'] + rect['height']
    
    for wall in walls:
        # ピクセル座標に変換
        x1_px = int((wall['start'][0] - min_x) * scale) + margin
        y1_px = img_height - (int((wall['start'][1] - min_y) * scale) + margin)
        x2_px = int((wall['end'][0] - min_x) * scale) + margin
        y2_px = img_height - (int((wall['end'][1] - min_y) * scale) + margin)
        
        # 両端点が四角形内にあるかチェック（許容値なし）
        if (x_rect_min <= x1_px <= x_rect_max and y_rect_min <= y1_px <= y_rect_max and
            x_rect_min <= x2_px <= x_rect_max and y_rect_min <= y2_px <= y_rect_max):
            filtered_walls.append(wall)
    
    return filtered_walls


def _line_intersects_rect(x1, y1, x2, y2, rect_or_left, rect_top=None, rect_right=None, rect_bottom=None, tolerance=0):
    """線分が四角形と交差または近接しているかチェック。
    互換性を持たせるため、以下の呼び出し形式の両方を受け入れます:
      - _line_intersects_rect(x1,y1,x2,y2, rect_dict, tolerance=...)
      - _line_intersects_rect(x1,y1,x2,y2, left, top, right, bottom)
    """

    # rect_or_left が辞書で渡された場合は展開
    if rect_top is None and isinstance(rect_or_left, dict):
        rect = rect_or_left
        rect_left = rect.get('left', 0)
        rect_top = rect.get('top', 0)
        rect_right = rect_left + rect.get('width', 0)
        rect_bottom = rect_top + rect.get('height', 0)
    else:
        # 数値で渡された場合
        rect_left = rect_or_left

    # 拡張判定: tolerance を四角形に適用して拡大する
    x_min = rect_left - tolerance
    y_min = rect_top - tolerance
    x_max = rect_right + tolerance
    y_max = rect_bottom + tolerance

    # 1. 端点が四角形内にある
    if (x_min <= x1 <= x_max and y_min <= y1 <= y_max) or \
       (x_min <= x2 <= x_max and y_min <= y2 <= y_max):
        return True

    # ヘルパ: 線分交差判定（2D、閉区間）
    def _on_segment(ax, ay, bx, by, cx, cy):
        return min(ax, bx) <= cx <= max(ax, bx) and min(ay, by) <= cy <= max(ay, by)

    def _orient(ax, ay, bx, by, cx, cy):
        return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)

    def _segments_intersect(a1, a2, b1, b2):
        ax1, ay1 = a1
        ax2, ay2 = a2
        bx1, by1 = b1
        bx2, by2 = b2
        o1 = _orient(ax1, ay1, ax2, ay2, bx1, by1)
        o2 = _orient(ax1, ay1, ax2, ay2, bx2, by2)
        o3 = _orient(bx1, by1, bx2, by2, ax1, ay1)
        o4 = _orient(bx1, by1, bx2, by2, ax2, ay2)

        if o1 == 0 and _on_segment(ax1, ay1, ax2, ay2, bx1, by1):
            return True
        if o2 == 0 and _on_segment(ax1, ay1, ax2, ay2, bx2, by2):
            return True
        if o3 == 0 and _on_segment(bx1, by1, bx2, by2, ax1, ay1):
            return True
        if o4 == 0 and _on_segment(bx1, by1, bx2, by2, ax2, ay2):
            return True

        return (o1 * o2 < 0) and (o3 * o4 < 0)

    # 2. 線分と四角形の4辺が交差しているか厳密に判定
    rect_edges = [
        ((x_min, y_min), (x_max, y_min)),  # top
        ((x_max, y_min), (x_max, y_max)),  # right
        ((x_max, y_max), (x_min, y_max)),  # bottom
        ((x_min, y_max), (x_min, y_min)),  # left
    ]

    seg_a = ((x1, y1), (x2, y2))
    for edge in rect_edges:
        if _segments_intersect(seg_a[0], seg_a[1], edge[0], edge[1]):
            return True

    # 3. 上記で判定できなければ重なりなし
    return False


def _filter_walls_by_endpoints_in_rect(walls, rect, scale, margin, img_height, min_x, min_y, max_x, max_y, tolerance=0, debug=False):
    """
    四角形範囲内に端点があるか、線分が四角形と交差する壁線を返す（窓追加モード用）
    
    Args:
        tolerance: 端点判定の許容範囲（ピクセル）デフォルト0px（誤検出防止）
        debug: Trueの場合、詳細なデバッグ情報を返す
    """
    filtered_walls = []
    debug_info = []
    
    x_rect_min = rect['left']
    x_rect_max = rect['left'] + rect['width']
    y_rect_min = rect['top']
    y_rect_max = rect['top'] + rect['height']
    
    if debug:
        debug_info.append(f"四角形範囲: X[{x_rect_min:.1f}, {x_rect_max:.1f}], Y[{y_rect_min:.1f}, {y_rect_max:.1f}]")
        debug_info.append(f"四角形サイズ: {rect['width']:.1f} x {rect['height']:.1f} px")
        if tolerance > 0:
            debug_info.append(f"許容範囲: ±{tolerance}px")
        debug_info.append(f"検証対象の壁数: {len(walls)}本")
        debug_info.append("---")
    
    for wall in walls:
        # ピクセル座標に変換
        x1_px = int((wall['start'][0] - min_x) * scale) + margin
        y1_px = img_height - (int((wall['start'][1] - min_y) * scale) + margin)
        x2_px = int((wall['end'][0] - min_x) * scale) + margin
        y2_px = img_height - (int((wall['end'][1] - min_y) * scale) + margin)
        
        # 端点が四角形内にあるかチェック
        start_in_rect = (
            x_rect_min - tolerance <= x1_px <= x_rect_max + tolerance and 
            y_rect_min - tolerance <= y1_px <= y_rect_max + tolerance
        )
        end_in_rect = (
            x_rect_min - tolerance <= x2_px <= x_rect_max + tolerance and 
            y_rect_min - tolerance <= y2_px <= y_rect_max + tolerance
        )
        
        # 線分が四角形と交差するかチェック
        intersects = _line_intersects_rect(
            x1_px, y1_px, x2_px, y2_px,
            x_rect_min, y_rect_min, x_rect_max, y_rect_max
        )
        
        matched = start_in_rect or end_in_rect or intersects
        
        if debug:
            wall_id = wall.get('id', '?')
            reasons = []
            if start_in_rect:
                reasons.append("始点✓")
            if end_in_rect:
                reasons.append("終点✓")
            if intersects and not (start_in_rect or end_in_rect):
                reasons.append("交差✓")
            
            reason_str = ",".join(reasons) if reasons else "範囲外✗"
            
            # 検出された壁のみ、または全壁を表示（最初の50本まで）
            if matched or len(debug_info) < 60:  # ヘッダー行+最大50壁
                debug_info.append(
                    f"壁#{wall_id}: start({x1_px:.0f},{y1_px:.0f}) end({x2_px:.0f},{y2_px:.0f}) → {reason_str}"
                )
        
        if matched:
            filtered_walls.append(wall)
    
    if debug:
        return filtered_walls, debug_info
    return filtered_walls


def main():
    st.set_page_config(page_title="一条工務店 CAD図面3D化アプリ (β)", layout="wide")
    st.title("一条工務店 CAD図面3D化アプリ (β)")
    st.caption("アップロードした図面は一時的な処理にのみ使用し、データベースに保存されることはありません。")
    
    # 固定画像幅（自動結合と手動編集で統一）
    DISPLAY_IMAGE_WIDTH = 800

    # セッション状態の初期化（結果の永続化）
    if "processed" not in st.session_state:
        st.session_state.processed = False
    for key in [
        "out_dir", "refined_img", "refined_name", "refined_bytes", "json_bytes", "json_name",
        "viz_bytes", "viz_name", "viewer_html_bytes", "viewer_html_name",
        "zip_bytes", "zip_name", "merged_json_bytes", "merged_json_name", "merged_viz_bytes", "merged_viz_name",
        "merged_processed"
    ]:
        st.session_state.setdefault(key, None)
    if "merged_processed" not in st.session_state:
        st.session_state.merged_processed = False
    if "workflow_step" not in st.session_state:
        st.session_state.workflow_step = 1  # 1:読み込み, 2:スケール校正, 3:手動編集
        # debug: record initialization
        st.session_state.setdefault('debug_log', []).append(f"init: set workflow_step=1")
    if "merge_choice" not in st.session_state:
        st.session_state.merge_choice = "自動壁結合を実行"
    if "viz_scale" not in st.session_state:
        st.session_state.viz_scale = 100  # 可視化スケール（メートル→ピクセル）固定値
    
    # 壁選択用のセッション状態（各編集モード用）
    if "selected_walls_for_merge" not in st.session_state:
        st.session_state.selected_walls_for_merge = []  # 線を結合モード：選択された壁のリスト（最大2本）
    if "selected_walls_for_window" not in st.session_state:
        st.session_state.selected_walls_for_window = []  # 窓を追加モード：選択された壁のリスト（最大2本）
    if "selected_walls_for_delete" not in st.session_state:
        st.session_state.selected_walls_for_delete = []  # 線を削除モード：選択された壁のリスト（無制限）

    # 2D可視化スケールを固定値に設定
    viz_scale = 100

    # 永続デバッグログ初期化とヘルパー
    if 'debug_log' not in st.session_state:
        st.session_state['debug_log'] = []
    # (internal debug_log retained in session_state; no UI display)

    # 3D表示用expanderの開閉状態を管理
    if 'open_3d_expander' not in st.session_state:
        st.session_state['open_3d_expander'] = False

    # --- debug helper: callback to set workflow step reliably ---
    def _set_workflow_step(n: int, open_3d: bool = False):
        st.session_state.setdefault('debug_log', []).append(f"callback: set_workflow {n} (was {st.session_state.get('workflow_step')})")
        st.session_state.workflow_step = n
        if open_3d:
            st.session_state.open_3d_expander = True
        st.session_state.setdefault('debug_log', []).append(f"callback: workflow_step now {st.session_state.get('workflow_step')}")

    # manual debug button removed

    def append_debug(msg: str):
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.session_state.setdefault('debug_logs', []).append(f"{ts} {msg}")
        except Exception:
            # append に失敗しても処理継続
            pass
    
    st.divider()

    # ============= ステップ1: 画像読み込み =============
    with st.expander("Step 1：画像読み込み", expanded=(st.session_state.workflow_step == 1)):
        st.markdown("## ステップ ①  画像読み込み")

        # 最初のステップの説明
        st.info(
            "間取り図のPDF（またはJPG/PNG）をアップロードしてください。\n\n"
            # "• **PDF**: 図面アプリから出力したPDFファイル\n\n"
            # "• **JPG/PNG**: スキャン画像やスクリーンショット"
        )

        uploaded = st.file_uploader("図面PDF/画像をアップロード", type=["pdf", "jpg", "jpeg", "png"], accept_multiple_files=False)
    
        # PDFの場合、ページ数を確認してページ選択UIを表示
        page_number = 0  # デフォルト
        if uploaded is not None and uploaded.name.lower().endswith('.pdf'):
            try:
                # 一時的にPDFを保存してページ数を取得
                temp_pdf = io.BytesIO(uploaded.getvalue())
                doc = fitz.open(stream=temp_pdf, filetype="pdf")
                total_pages = len(doc)
                doc.close()
                
                if total_pages > 1:
                    # st.info(f"📄 このPDFは {total_pages} ページあります。処理するページを選択してください。")
                    page_number = st.selectbox(
                        "処理するページを選択",
                        options=list(range(total_pages)),
                        format_func=lambda x: f"ページ {x + 1}",
                        help="PDFの何ページ目を処理するか選択します（0始まり）"
                    )
                else:
                    st.info("📄 このPDFは 1 ページです。")
            except Exception as e:
                st.warning(f"PDFページ数の取得に失敗しました: {e}")
        
        # if uploaded is None and not st.session_state.processed:
        #     st.info("PDF/JPG/PNGをアップロードしてください。")
        
        # アップロード後のパラメータ設定を折りたたみで表示
        if uploaded is not None or st.session_state.processed:
            with st.expander("⚙️ **パラメータ設定（必要に応じて修正）**", expanded=False):
                # 3列レイアウト
                col1, col2, col3 = st.columns(3)
                
                # 列1: 除外範囲設定
                with col1:
                    st.subheader("✂️ 除外範囲")
                    st.markdown("#### 外枠・ロゴ除外")
                    with st.expander("💡 使い方", expanded=False):
                        st.markdown(
                            "**調整方法:**\n\n"
                            "- PDFの外枠、タイトル、ロゴを除外\n\n"
                            "- 中心部の間取り図だけを処理\n\n"
                            "- 除外が少ない → 値を上げる\n\n"
                            "- 図面が欠ける → 値を下げる"
                        )
                    
                    margin_vertical = st.slider(
                        "上下除外(%)",
                        min_value=0,
                        max_value=30,
                        value=10,
                        step=1,
                        help="上下の外枠・タイトル・ロゴを除外します。"
                    )
                    
                    margin_horizontal = st.slider(
                        "左右除外(%)",
                        min_value=0,
                        max_value=30,
                        value=10,
                        step=1,
                        help="左右の外枠・ロゴを除外します。"
                    )
                
                # 列2: 壁検出パラメータ(黒閾値、最小線幅)
                with col2:
                    st.subheader("🎨 壁パラメータ")
                    
                    #st.markdown("#### 黒線認識の閾値")
                    #with st.expander("💡 調整のコツ", expanded=False):
                    #    st.markdown(
                    #        "**調整方法:**\n\n"
                    #        "1. 最初は190から試す\n\n"
                    #        "2. ノイズが多い → 値を下げる\n\n"
                    #        "3. 薄い線が消える → 値を上げる"
                    #    )
                    
                    #black_threshold = st.slider(
                    #    "黒閾値",
                    #    min_value=100,
                    #    max_value=240,
                    #    value=190,
                    #    step=5,
                    #    help="値を上げる = 薄い線も拾う。値を下げる = 濃い線のみ。"
                    #)
                    black_threshold = 190  # 固定値に変更

                    st.markdown("#### 最小認識 黒線幅")
                    with st.expander("💡 調整のコツ", expanded=False):
                        st.markdown(
                            "**調整方法:**\n\n"
                            "1. 壁が多すぎる → 値を上げる\n\n"
                            "2. 壁が足りない → 値を下げる"
                        )
                    
                    min_thickness = st.slider(
                        "最小線幅(px)",
                        min_value=3,
                        max_value=20,
                        value=10,
                        step=1,
                        help="小さい = 細い線も拾う。大きい = 太い線のみ。DPI高い時は大きく。"
                    )
                
                # 列3: 出力スケール(壁高さ)
                with col3:
                    st.subheader("🏗️ 出力スケール")
                    wall_height = st.number_input(
                        "壁(天井)高さ",
                        min_value=0.1,
                        max_value=10.0,
                        value=2.4,
                        step=0.1,
                        help="部屋の天井高さ（床から天井までの高さ）をメートル単位で指定します。一般的な住宅は2.4m程度です。"
                    )
                
                # PDFレンダリングDPI（固定値に変更）
                dpi = 300
                
                # ピクセル→メートル係数: スケール校正済みの値があればそれを使用、なければデフォルト値
                if "json_bytes" in st.session_state and st.session_state.json_bytes:
                    try:
                        json_data = json.loads(st.session_state.json_bytes.decode("utf-8"))
                        pixel_to_meter = json_data.get("metadata", {}).get("pixel_to_meter", 0.005) or 0.005
                        if pixel_to_meter != 0.005:
                            st.info(f"📐 スケール校正済みの値を使用: pixel_to_meter = {pixel_to_meter:.6f}")
                    except:
                        pixel_to_meter = 0.005
                else:
                    pixel_to_meter = 0.005
            
            # ステップ1: 変換実行ボタン
            col_run, col_skip = st.columns([2, 1])
            with col_run:
                run = st.button("🚀 変換を実行", type="primary", use_container_width=True, key="step1_run")
            with col_skip:
                if st.button("⏭️ スキップ", use_container_width=True, key="step1_skip"):
                    st.session_state.workflow_step = 2
                    st.rerun()
        else:
            # アップロード前のデフォルト値を設定
            dpi = 300
            black_threshold = 190
            min_thickness = 8
            pixel_to_meter = 0.005
            wall_height = 2.4
            margin_vertical = 10
            margin_horizontal = 5
            run = False

        # 途中経過の表示可否（Falseで最終結果のみ表示）
        show_progress = False

        if run:
            if uploaded is None:
                st.error("ファイルが未選択です。先にPDF/画像をアップロードしてください。")
                st.stop()
            # 出力ディレクトリ（タイムスタンプで分離）
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_dir = OUTPUTS_DIR / f"run_{ts}"
            out_dir.mkdir(parents=True, exist_ok=True)

            # 入力ファイル保存
            input_suffix = Path(uploaded.name).suffix.lower()
            input_path = out_dir / f"input{input_suffix}"
            _save_uploaded_file(uploaded, input_path)
            if show_progress:
                st.success(f"入力を保存: {input_path}")

            # PDFなら画像へレンダリング
            if input_suffix == ".pdf":
                if show_progress:
                    st.write(f"PDFを画像に変換中… (ページ {page_number + 1})")
                source_image = out_dir / "source.png"
                pdf_to_image(str(input_path), output_path=str(source_image), page_number=page_number, dpi=dpi)
                image_path = source_image
            else:
                image_path = input_path

            if show_progress:
                st.write("壁線抽出とノイズ除去を実行中…")
            try:
                refined_img, refined_path = refine_floor_plan_from_image(
                    str(image_path), 
                    black_threshold=black_threshold, 
                    min_thickness=min_thickness, 
                    remove_corners=False,
                    margin_vertical=margin_vertical,
                    margin_horizontal=margin_horizontal
                )
                refined_path = Path(refined_path)
                
                # refined画像をout_dirに移動
                refined_dest = out_dir / refined_path.name
                if refined_path.exists() and refined_path != refined_dest:
                    refined_path.rename(refined_dest)
                    refined_path = refined_dest
                    if show_progress:
                        st.success(f"壁線抽出完了: {refined_path.name}")
            except Exception as e:
                st.error(f"壁線抽出でエラー: {e}")
                return

            # 3D JSON 生成
            if show_progress:
                st.write("3D座標JSONを生成中…")
            json_path = out_dir / "walls_3d.json"
            try:
                result = process_image_to_3d(str(refined_path), str(json_path), wall_height=wall_height, pixel_to_meter=pixel_to_meter)
                if result is None:
                    st.error("❌ 3D座標の生成に失敗しました。")
                    st.warning("⚠️ 原因: refined画像から壁線が検出できませんでした。")
                    st.info(
                        "**対策:**\n\n"
                        "- 最小線幅を大きくする（8-12px推奨）\n\n"
                        "- 黒閾値を調整する（190-210推奨）\n\n"
                        "- DPIを上げる（400-600推奨）"
                    )
                    # デバッグ用：refined画像が実際に存在するか確認
                    if refined_path.exists():
                        st.info(f"✓ refined画像は生成されています: {refined_path.name}")
                    return
            except Exception as e:
                st.error(f"❌ 3D座標生成でエラー: {e}")
                import traceback
                st.code(traceback.format_exc())
                return

            # 2D可視化
            if show_progress:
                st.write("2D可視化画像を生成中…")
            viz_path = out_dir / "visualization.png"
            try:
                canvas = visualize_3d_walls(str(json_path), str(viz_path), scale=int(viz_scale), wall_color=(0, 0, 0), bg_color=(255, 255, 255))
            except Exception as e:
                canvas = None
                st.warning(f"可視化の生成に失敗しました: {e}")

            # Three.js HTMLビューア生成
            if show_progress:
                st.write("3DビューアHTMLを生成中…")
            viewer_html = out_dir / "viewer_3d.html"
            try:
                _generate_3d_viewer_html(json_path, viewer_html)
            except Exception as e:
                st.error(f"3DビューアHTML生成でエラー: {e}")
                return

            # セッションに結果を保存（ダウンロードで再実行されても残す）
            st.session_state.out_dir = str(out_dir)
            st.session_state.refined_img = refined_img
            st.session_state.refined_name = refined_path.name
            st.session_state.refined_bytes = refined_path.read_bytes()
            st.session_state.json_bytes = json_path.read_bytes()
            st.session_state.json_name = json_path.name
            st.session_state.viewer_html_bytes = viewer_html.read_bytes()
            st.session_state.viewer_html_name = viewer_html.name
            if canvas is not None and viz_path.exists():
                st.session_state.viz_bytes = viz_path.read_bytes()
                st.session_state.viz_name = viz_path.name
            else:
                st.session_state.viz_bytes = None
                st.session_state.viz_name = None
            
            # ====== 自動結合を実行 ======
            try:
                # デフォルトを 30px に変更して誤結合を抑制
                merge_radius = st.session_state.get("merge_radius", 55)
                merge_angle = st.session_state.get("merge_angle", 15)
                
                merged_json_path = out_dir / "walls_3d_merged.json"
                merged_viz_path = out_dir / "visualization_merged.png"
                
                # (表示削除) 自動結合で使用するパラメータの情報表示を削除しました
                merger = WallAutoMerger(search_radius=merge_radius, angle_tolerance=merge_angle)
                merger.process(str(refined_path), str(json_path), str(merged_json_path))
                
                visualize_3d_walls(
                    str(merged_json_path),
                    str(merged_viz_path),
                    scale=int(viz_scale),
                    wall_color=(0, 0, 0),
                    bg_color=(255, 255, 255)
                )
                
                merged_viewer_path = out_dir / "viewer_3d_merged.html"
                _generate_3d_viewer_html(merged_json_path, merged_viewer_path)
                
                st.session_state.merged_json_bytes = merged_json_path.read_bytes()
                st.session_state.merged_json_name = merged_json_path.name
                if merged_viz_path.exists():
                    st.session_state.merged_viz_bytes = merged_viz_path.read_bytes()
                    st.session_state.merged_viz_name = merged_viz_path.name
                if merged_viewer_path.exists():
                    st.session_state.merged_viewer_html_bytes = merged_viewer_path.read_bytes()
                    st.session_state.merged_viewer_html_name = merged_viewer_path.name
                
                # 結合済みファイルを作業ファイルとして設定
                st.session_state.json_bytes = merged_json_path.read_bytes()
                st.session_state.json_name = merged_json_path.name
                st.session_state.viz_bytes = merged_viz_path.read_bytes()
                st.session_state.viz_name = merged_viz_path.name
                st.session_state.viewer_html_bytes = merged_viewer_path.read_bytes()
                st.session_state.viewer_html_name = merged_viewer_path.name
                st.session_state.merged_processed = True
            except Exception as e:
                st.warning(f"⚠️ 自動結合でエラー: {e}")
                st.session_state.merged_processed = False
            
            # ZIP生成（JSON+抽出PNG+3DビューアHTML）
            try:
                zip_buf = io.BytesIO()
                with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr(st.session_state.json_name, st.session_state.json_bytes)
                    zf.writestr(st.session_state.viewer_html_name, st.session_state.viewer_html_bytes)
                    if st.session_state.refined_bytes and st.session_state.refined_name:
                        zf.writestr(st.session_state.refined_name, st.session_state.refined_bytes)
                zip_buf.seek(0)
                st.session_state.zip_bytes = zip_buf.getvalue()
                st.session_state.zip_name = f"{out_dir.name}_bundle.zip"
            except Exception:
                st.session_state.zip_bytes = None
                st.session_state.zip_name = None
            st.session_state.processed = True
            # st.success("変換が完了しました！")

            # セッションに結果があれば常に表示（ダウンロードでの再実行でも消えない）
            if st.session_state.processed:
                st.session_state.setdefault('debug_log', []).append(
                    f"render: entering processed block (workflow_step={st.session_state.get('workflow_step')}, processed={st.session_state.get('processed')}, viewer_html={'yes' if st.session_state.get('viewer_html_bytes') else 'no'})"
                )
                # 3Dモデル用イメージを先に表示
                st.subheader("📊 3Dモデル用イメージ")
                if st.session_state.viz_bytes is not None:
                    # 画面サイズの50%に縮小表示（左寄せ）
                    col1, col2 = st.columns([0.5, 0.5])
                    with col1:
                        st.image(st.session_state.viz_bytes, use_container_width=True)

                # 壁線抽出結果はexpanderの中に格納（デフォルトで閉じる）
                with st.expander("🖼️ 壁線抽出結果（CAD図面参照）", expanded=False):
                    if st.session_state.refined_img is not None:
                        # 画面サイズの50%に縮小表示（左寄せ）
                        col1, col2 = st.columns([0.5, 0.5])
                        with col1:
                            st.image(st.session_state.refined_img, clamp=True, use_container_width=True)

                # 説明文を追加
                st.success(
                    "変換完了！ 壁の分断や過不足がある場合はパラメータを手動調整して再変換するか、手動編集で修正可能です。\n\n"
                    "窓は手動編集で追加できます。"
                )

                # 3DビューアHTMLダウンロードボタン
                #if st.session_state.viewer_html_bytes:
                #    st.download_button(
                #        label="3Dモデルをダウンロード",
                #        data=st.session_state.viewer_html_bytes,
                #        file_name=st.session_state.viewer_html_name,
                #        mime="text/html"
                #    )

                # ステップ1: 読み取り完了ボタン（左寄せ、押すとStep2へ遷移）
                # ステップ1: 読み取り完了ボタン（左寄せ、押すとStep2へ遷移し3D表示を開く）
                st.session_state.setdefault('debug_log', []).append("render: before creating step1_complete button")
                # ボタン列幅を広げ、ボタンをコンテナ幅いっぱいに表示して折返しを防止
                col_btn, col_rest = st.columns([3, 7])
                with col_btn:
                    #st.button("✅ 読み取り完了", type="primary", key="step1_complete", on_click=_set_workflow_step, args=(2,), use_container_width=True)
                    st.button("✅ 読み取り完了", type="primary", key="step1_complete", on_click=_set_workflow_step, args=(2, True), use_container_width=True)


    with st.expander("Step 2：スケール校正", expanded=(st.session_state.workflow_step == 2)):
        if st.session_state.workflow_step >= 2 and st.session_state.processed:
            st.divider()
            st.markdown("## ステップ ②  スケール校正")
        st.info(
            "基準となる壁を選択して、修正スケール値を入力して実行してください。(一条CAD図面 1マス = 編集画面 2マス推奨)\n\n"
            "変更ない場合は「スキップして次へ」を選択してください"
        )

        # 壁選択用の簡易編集エリアを即時表示
        #st.caption("壁線を1回クリックすると赤色にハイライトします。選択しない場合はスキップで次へ進めます。")

        # 初期化
        if "selected_wall_for_calibration" not in st.session_state:
            st.session_state.selected_wall_for_calibration = None
        if "scale_last_click" not in st.session_state:
            st.session_state.scale_last_click = None

        if st.session_state.viz_bytes:
            try:
                import math
                from PIL import ImageDraw

                disp_img, scale_disp, orig_w, orig_h = _prepare_display_from_bytes(
                    st.session_state.viz_bytes, max_width=DISPLAY_IMAGE_WIDTH
                )

                # 壁データ読み込みと座標変換（streamlit_app.pyと同じロジック）
                json_data = json.loads(st.session_state.json_bytes.decode("utf-8"))
                walls = json_data.get("walls", [])
                scale_px = int(st.session_state.viz_scale)
                margin = 50  # streamlit_app.pyと同じマージン
                all_x, all_y = [], []
                for w in walls:
                    s = w.get("start", [])
                    e = w.get("end", [])
                    if len(s) >= 2 and len(e) >= 2:
                        all_x.extend([s[0], e[0]])
                        all_y.extend([s[1], e[1]])
                if all_x and all_y:
                    min_x, max_x = min(all_x), max(all_x)
                    min_y, max_y = min(all_y), max(all_y)
                    # visualization画像のサイズを計算（Y座標反転を考慮）
                    img_width_calc = int((max_x - min_x) * scale_px) + 2 * margin
                    img_height_calc = int((max_y - min_y) * scale_px) + 2 * margin
                else:
                    min_x = min_y = 0
                    max_x = max_y = 1
                    img_width_calc = orig_w
                    img_height_calc = orig_h

                # オーバーレイ描画用にコピー
                overlay = disp_img.copy()
                draw = ImageDraw.Draw(overlay)

                # 選択された壁をハイライト表示
                target_wall_data = None
                px_distance = None
                if st.session_state.selected_wall_for_calibration:
                    selected_wall = st.session_state.selected_wall_for_calibration
                    s = selected_wall.get("start", [])
                    e = selected_wall.get("end", [])
                    if len(s) >= 2 and len(e) >= 2:
                        # メートル→ピクセル変換（Y座標反転を考慮）
                        x1 = int((s[0] - min_x) * scale_px) + margin
                        y1 = img_height_calc - (int((s[1] - min_y) * scale_px) + margin)
                        x2 = int((e[0] - min_x) * scale_px) + margin
                        y2 = img_height_calc - (int((e[1] - min_y) * scale_px) + margin)

                        # 表示座標で赤線を描画
                        dx1 = int(x1 * scale_disp)
                        dy1 = int(y1 * scale_disp)
                        dx2 = int(x2 * scale_disp)
                        dy2 = int(y2 * scale_disp)
                        draw.line((dx1, dy1, dx2, dy2), fill=(255, 0, 0), width=4)

                        # 壁データを準備
                        wall_length_px = math.hypot(x2 - x1, y2 - y1)
                        target_wall_data = {
                            'wall': selected_wall,
                            'id': selected_wall.get('id', '?'),
                            'length_px': wall_length_px,
                            'start_m': s,
                            'end_m': e
                        }
                        px_distance = wall_length_px

                    # スケール入力と反映
                    if px_distance is not None and target_wall_data is not None:
                        # マス数入力フォーム
                        default_grid = st.session_state.get("step3_grid_input_val", 1.0)
                    grid_count = st.number_input(
                        "この壁は一条工務店CAD図面上で何マス分ですか？ (1マス=0.9m)",
                        min_value=0.1,
                        max_value=100.0,
                        value=float(default_grid),
                        step=0.1,
                        key="step3_grid_input"
                    )
                    st.session_state.step3_grid_input_val = grid_count
                    
                    if st.button("💾 このスケールで更新", type="primary", use_container_width=True, key="step3_apply_scale"):
                        try:
                            # 実測距離（メートル単位）
                            actual_distance_m = grid_count * 0.9  # 1マス = 0.9m = 90cm
                            
                            # 現在の壁の長さ（メートル単位）を取得
                            current_length_m = target_wall_data['wall'].get('length')
                            if current_length_m is None:
                                dx_m = target_wall_data['end_m'][0] - target_wall_data['start_m'][0]
                                dy_m = target_wall_data['end_m'][1] - target_wall_data['start_m'][1]
                                current_length_m = math.sqrt(dx_m**2 + dy_m**2)
                            
                            if current_length_m <= 0:
                                st.error("❌ 現在の壁長が0mのため再計算できません。別の壁で試してください。")
                            else:
                                # スケール比率を計算（実測/現在）
                                scale_ratio = actual_distance_m / current_length_m
                                
                                # 現在のJSONを読み込み
                                import copy
                                out_dir = Path(st.session_state.out_dir)
                                json_path = out_dir / st.session_state.json_name
                                json_data = json.loads(st.session_state.json_bytes.decode("utf-8"))
                                old_pixel_to_meter = json_data.get("metadata", {}).get("pixel_to_meter", 0.005) or 0.005
                                
                                # 新しいpixel_to_meterを計算
                                new_pixel_to_meter = old_pixel_to_meter * scale_ratio
                                
                                # 各壁の座標をスケール変換
                                calibrated_json = copy.deepcopy(json_data)
                                for wall in calibrated_json.get("walls", []):
                                    if "start" in wall and "end" in wall:
                                        # 座標をスケール変換（X-Y平面のみ）
                                        wall["start"] = [round(wall["start"][0] * scale_ratio, 3),
                                                       round(wall["start"][1] * scale_ratio, 3)]
                                        wall["end"] = [round(wall["end"][0] * scale_ratio, 3),
                                                     round(wall["end"][1] * scale_ratio, 3)]
                                        # 長さを再計算（X-Y平面の長さ）
                                        dx = wall["end"][0] - wall["start"][0]
                                        dy = wall["end"][1] - wall["start"][1]
                                        wall["length"] = round(math.sqrt(dx**2 + dy**2), 3)
                                        
                                        # 高さは2.4m固定（スケール変換しない）
                                        # 一条工務店の標準天井高は2.4mで固定
                                        if "height" not in wall or wall.get("height") != 2.4:
                                            wall["height"] = 2.4
                                        
                                        # 厚さは10cm固定（スケール変換しない）
                                        # 一条工務店の標準壁厚は10cmで固定
                                        wall["thickness"] = 0.1
                                
                                # メタデータを更新
                                calibrated_json.setdefault("metadata", {})["pixel_to_meter"] = new_pixel_to_meter
                                
                                # デバッグ情報：校正後の座標範囲を計算
                                all_x_after = []
                                all_y_after = []
                                for w in calibrated_json.get("walls", []):
                                    if "start" in w and "end" in w:
                                        all_x_after.extend([w["start"][0], w["end"][0]])
                                        all_y_after.extend([w["start"][1], w["end"][1]])
                                
                                if all_x_after and all_y_after:
                                    min_x_after, max_x_after = min(all_x_after), max(all_x_after)
                                    min_y_after, max_y_after = min(all_y_after), max(all_y_after)
                                    width_after = max_x_after - min_x_after
                                    height_after = max_y_after - min_y_after
                                
                                # 保存と再可視化
                                json_path.write_text(json.dumps(calibrated_json, indent=2, ensure_ascii=False))
                                st.session_state.json_bytes = json_path.read_bytes()
                                viz_path = out_dir / st.session_state.viz_name
                                visualize_3d_walls(
                                    str(json_path),
                                    str(viz_path),
                                    scale=int(st.session_state.viz_scale),
                                    wall_color=(0, 0, 0),
                                    bg_color=(255, 255, 255)
                                )
                                if viz_path.exists():
                                    st.session_state.viz_bytes = viz_path.read_bytes()

                                # 後続用に状態更新
                                st.session_state.scale_calibration_done = True
                                st.session_state.selected_wall_for_calibration = None
                                st.session_state.scale_last_click = None
                                st.session_state.step3_grid_input_val = grid_count
                                # 3D表示を開く
                                st.session_state.open_3d_expander = True
                                # 手動編集へ遷移
                                st.session_state.workflow_step = 3
                                st.rerun()
                        except Exception as e:
                            st.error(f"❌ スケール更新でエラーが発生しました: {e}")
                            import traceback
                            st.code(traceback.format_exc())

                # ズームコントロール（ステップ2）
                if 'editor_zoom_level' not in st.session_state:
                    st.session_state.editor_zoom_level = 1.0
                
                col_zoom_label, col_zoom1, col_zoom2, col_zoom_space = st.columns([3, 1, 1, 7])
                with col_zoom_label:
                    st.markdown(f"表示サイズ調整: {st.session_state.editor_zoom_level*100:.0f}%")
                with col_zoom1:
                    if st.button("🔍−", key="step2_zoom_out"):
                        st.session_state.editor_zoom_level = max(0.2, st.session_state.editor_zoom_level - 0.2)
                        st.rerun()
                with col_zoom2:
                    if st.button("🔍+", key="step2_zoom_in"):
                        st.session_state.editor_zoom_level = min(1.6, st.session_state.editor_zoom_level + 0.2)
                        st.rerun()
                
                
                # ズーム適用
                zoom_level = st.session_state.get('editor_zoom_level', 1.0)
                if zoom_level != 1.0:
                    w, h = overlay.size
                    overlay_resized = overlay.resize(
                        (int(w * zoom_level), int(h * zoom_level)),
                        Image.Resampling.LANCZOS
                    )
                else:
                    overlay_resized = overlay
                
                # 画像データの検証（表示エラー対策 - ステップ3と同じロジック）
                if overlay_resized is None:
                    st.warning("⚠️ 画像データを再生成しています...")
                    st.rerun()
                
                if overlay_resized.size[0] == 0 or overlay_resized.size[1] == 0:
                    st.warning("⚠️ 画像サイズが不正です。再試行しています...")
                    # ズームレベルをリセット
                    st.session_state.editor_zoom_level = 1.0
                    st.rerun()
                
                # 注釈を表示（ステップ3と同じ）
                st.markdown(
                    """
                    <p style="font-size: 12px; color: #666; margin-bottom: 8px;">
                    <b>注:</b> 編集画面が表示されないときは選択リセットか表示サイズ調整を押してください。
                    </p>
                    """,
                    unsafe_allow_html=True
                )
                
                # キーを動的に生成（ステップ3と同様に状態を反映）
                if 'calibration_reset_counter' not in st.session_state:
                    st.session_state.calibration_reset_counter = 0
                
                selected_wall_id = st.session_state.selected_wall_for_calibration.get('id', 'none') if st.session_state.selected_wall_for_calibration else 'none'
                calib_key = f"step2_calib_click_{selected_wall_id}_{st.session_state.calibration_reset_counter}"

                # クリック受付（表示画像）
                click = streamlit_image_coordinates(overlay_resized, key=calib_key)

                # クリック処理（壁選択方式 - ステップ3と同じ座標変換ロジック）
                if click and click.get("x") is not None:
                    cur = (click["x"], click["y"])
                    if st.session_state.scale_last_click != cur:
                        st.session_state.scale_last_click = cur
                        
                        # ズーム補正を適用（ステップ3と同じロジック）
                        zoom_level = st.session_state.get('editor_zoom_level', 1.0)
                        adjusted_x = click["x"] / zoom_level
                        adjusted_y = click["y"] / zoom_level
                        
                        # 元の座標に変換（ステップ3と同じ _display_to_original 関数を使用）
                        if scale_disp != 1.0:
                            orig_click_x, orig_click_y = _display_to_original(adjusted_x, adjusted_y, scale_disp)
                        else:
                            orig_click_x = adjusted_x
                            orig_click_y = adjusted_y
                        
                        # クリック位置から最も近い壁を検出（元画像の座標系で）
                        nearest_wall, distance = _find_nearest_wall_from_click(
                            int(orig_click_x), int(orig_click_y),
                            walls, scale_px, margin,
                            img_height_calc, min_x, min_y, max_x, max_y,
                            threshold=20
                        )
                        
                        if nearest_wall:
                            # 壁を選択
                            st.session_state.selected_wall_for_calibration = nearest_wall
                        else:
                            # 閾値外の場合は選択解除
                            st.session_state.selected_wall_for_calibration = None
                        
                        st.rerun()

                col_reset = st.columns(2)[0]
                with col_reset:
                    if st.button("🔄 選択をリセット", use_container_width=True, key="step3_calib_reset"):
                        st.session_state.selected_wall_for_calibration = None
                        st.session_state.scale_last_click = None
                        st.session_state.calibration_reset_counter = st.session_state.get('calibration_reset_counter', 0) + 1
                        st.rerun()

                # スケール適用済みの案内（遷移は適用時に実施済み）
                if st.session_state.get("scale_calibration_done"):
                    st.success("スケールを適用しました。手動編集に進んでください。")
            except Exception as e:
                st.error(f"スケール校正ビュー表示エラー: {e}")
            
            # スキップして次へボタンを最後に配置
            if st.button("⏭️ スキップして次へ", use_container_width=True, key="step3_skip"):
                st.session_state.workflow_step = 3
                st.session_state.open_3d_expander = True
                st.rerun()
    # ============= ステップ3: 手動編集 =============
    with st.expander("Step 3：手動編集", expanded=(st.session_state.workflow_step == 3)):
        if st.session_state.workflow_step >= 3 and st.session_state.processed:
            st.divider()
            st.markdown("## ステップ ③ 手動編集")
        # --- 自動結合の現在値表示と再実行ボタン ---
        # 自動結合の手動操作UIは不要のため削除しました。
        # 固定パラメータを使用します: merge_radius=55px, merge_angle=15°
        cur_merge_radius = 55
        cur_merge_angle = 15
        merged_flag = st.session_state.get('merged_processed', False)
        # st.write("壁線を手動で編集・調整します。")
        
        # モード選択タブ
        edit_mode = st.radio(
            "編集モードを選択:",
            #["線を結合", "線を追加", "線を削除", "窓を追加", "照明を配置", "オブジェクトを配置", "床を追加", "階段を配置"],
            ["線を結合", "線を追加", "線を削除", "窓を追加", "オブジェクトを配置", "階段を配置"],
            horizontal=True,
            #help="線を結合：2つの壁線を繋ぐ\n\n窓を追加：窓で分断された2本の壁を上下の壁で繋ぐ\n\n線を追加：新しい壁線を追加\n\n線を削除：選択範囲の壁を削除\n\n照明を配置：クリック位置にスポットライトを配置\n\nオブジェクトを配置：キッチンボードなどの家具を配置\n\n床を追加：四角形範囲を選択して床を追加\n\n階段を配置：コの字階段を配置"
            help="線を結合：2つの壁線を繋ぐ\n\n線を追加：新しい壁線を追加\n\n線を削除：選択範囲の壁を削除\n\n窓を追加：窓で分断された2本の壁を上下の壁で繋ぐ\n\nオブジェクトを配置：キッチンボードなどの家具を配置\n\n階段を配置：コの字階段を配置"
        )
        
        if edit_mode == "線を結合":
            st.write("💡 結合したい2本の壁線を選択してください。（複数選択可能）" )
        elif edit_mode == "窓を追加":
            st.write("💡 窓追加したい2本の壁線を選択して、窓タイプを入力してください。（複数選択可能）")
        elif edit_mode == "線を追加":
            st.write("💡 追加したい壁の端点2点を指定してください。（複数選択可能）")
        elif edit_mode == "線を削除":
            st.write("💡 削除したい壁線をクリックしてください（複数選択可能）")
        elif edit_mode == "オブジェクトを配置":
            st.write("💡 オブジェクトを配置したい範囲(四角形)の対角線の2点を選択して、オブジェクトタイプを入力してください。")
        elif edit_mode == "階段を配置":
            st.write("💡 階段を配置したい範囲を2点クリックして選択し、階段パターンをプルダウンから選んでください")
        
        with st.expander("💡 使い方", expanded=False):
            if edit_mode == "線を結合":
                st.markdown(
                    "**複数線結合の手順:**\n\n"
                    "1. 下の画像上で結合したい**1本目の壁線をクリック**して選択\n\n"
                    "2. **2本目の壁線をクリック**して選択\n\n"
                    "3. さらに結合したい箇所があれば手順1-2を繰り返す（2本ずつペアで選択）\n\n"
                    "4. 「🔗 結合実行」で選択した全てのペアを一括結合\n\n"
                    "**ヒント:**\n\n"
                    "- 壁線を直接クリックするだけで選択できます\n\n"
                    "- 間違えた場合は同じ壁をもう一度クリックで選択解除"
                )
            elif edit_mode == "窓を追加":
                st.markdown(
                    "**窓追加の手順:**\n\n"
                    "1. 下の画像上で窓を追加したい**1本目の壁線をクリック**して選択\n\n"
                    "2. **2本目の壁線をクリック**して選択\n\n"
                    "3. さらに窓を追加したければ手順1-2を繰り返す\n\n"
                    "4. 窓のサイズを入力:\n\n"
                    "   - 窓の高さ（mm）: 例 1200mm\n\n"
                    "   - 床から窓下端までの高さ（mm）: 例 900mm\n\n"
                    "5. 「🪟 窓追加実行」で選択した全ての窓を一括追加\n\n"
                    "**ヒント:**\n\n"
                    "- 壁線を直接クリックするだけで選択できます\n\n"
                    "- 間違えた場合は同じ壁をもう一度クリックで選択解除\n\n"
                    "- 一条工務店の図面表記からそのまま入力可能"
                )
            elif edit_mode == "線を追加":
                st.markdown(
                    "**線追加の手順:**\n\n"
                    "1. 下の画像上で**2回クリック**して追加したい線の位置を選択する\n\n"
                    "2. さらに線を追加したければ手順1を繰り返す\n\n"
                    "3. 「➕ 線追加実行」で全ての選択範囲に線を追加\n\n"
                )
            elif edit_mode == "線を削除":
                st.markdown(
                    "**線削除の手順:**\n\n"
                    "1. 下の画像上で削除したい**壁線をクリック**して選択\n\n"
                    "2. さらに削除したい壁線があればクリックして追加\n\n"
                    "3. 「🗑️ 削除実行」で選択した全ての壁線を一括削除\n\n"
                    "**ヒント:**\n\n"
                    "- 壁線を直接クリックするだけで選択できます\n\n"
                    "- 間違えた場合は同じ壁をもう一度クリックで選択解除"
                )
            elif edit_mode == "オブジェクトを配置":
                st.markdown(
                    "**オブジェクト配置の手順:**\n\n"
                    "1. 下の画像上で**2回クリック**してオブジェクトを配置したい領域を四角形で囲む\n\n"
                    "2. 配置するオブジェクト高さと色を選択\n\n"
                    "3. 「🪑 オブジェクト配置実行」で家具を配置\n\n"
                    )
            elif edit_mode == "階段を配置":
                st.markdown(
                    "**階段配置の手順:**\n\n"
                    "1. 下の画像上で**2回クリック**して階段を配置したい領域を四角形で囲む\n\n"
                    "2. 階段パターンをプルダウンから選択\n\n"
                    "3. 「🪜 階段配置実行」で階段を配置\n\n"
                    "**注意:**\n\n"
                    "- コの字階段は実際の階段形状と異なります。"
                    )
        
        # セッションステートで四角形座標を管理
        if 'rect_coords' not in st.session_state:
            st.session_state.rect_coords = []
        if 'rect_coords_list' not in st.session_state:
            st.session_state.rect_coords_list = []  # 確定した四角形のリスト
        if 'reset_flag' not in st.session_state:
            st.session_state.reset_flag = False
        if 'last_click' not in st.session_state:
            st.session_state.last_click = None
        if 'merge_result' not in st.session_state:
            st.session_state.merge_result = None
        if 'edit_mode_state' not in st.session_state:
            st.session_state.edit_mode_state = "線を結合"  # 現在のモード

        # 窓追加用の入力フォーム（画面上部にまとめて表示）
        if edit_mode == "窓を追加":
            try:
                json_data_tmp = json.loads(st.session_state.json_bytes.decode("utf-8"))
                walls_tmp = json_data_tmp.get('walls', [])
                heights_tmp = [w.get('height', 2.4) for w in walls_tmp if 'height' in w]
                default_room_height = min(max(heights_tmp) if heights_tmp else 2.4, 10.0)
            except Exception:
                default_room_height = 2.4

            # 窓追加モード以外の場合のみ、上部に窓パラメータ入力を表示
            if edit_mode != "窓を追加":
                # 他のモード用の処理（必要に応じて）
                pass
        
        # 四角形の色定義（OpenCV BGRフォーマット）
        RECT_COLORS = [
            (255, 0, 0),      # 赤
            (0, 255, 0),      # 緑
            (0, 0, 255),      # 青
            (255, 255, 0),    # 黄
            (255, 0, 255),    # マゼンタ
            (0, 255, 255),    # シアン
        ]
        
        # 距離閾値（メートル）: 手動結合時に近接した別壁と誤結合しないよう、実用的な閾値を使用
        # 0.3m（30cm）程度に設定。必要に応じて調整してください。
        distance_threshold = 0.3
        
        # 編集結果の表示（セッション状態に保存されている場合）
        if st.session_state.merge_result is not None:
            result = st.session_state.merge_result
            
            st.success("🎉 編集完了！")
            st.markdown("### 📊 編集前後の比較")
            
            col_before, col_after = st.columns(2)
            with col_before:
                st.markdown("**編集前**")
                st.image(Image.open(io.BytesIO(result['original_viz_bytes'])), use_container_width=True)
            with col_after:
                st.markdown("**編集後**")
                st.image(Image.open(io.BytesIO(result['edited_viz_bytes'])), use_container_width=True)
            
            # 統計情報の比較
            st.markdown("### 📈 統計")
            col_stat1, col_stat2 = st.columns(2)
            with col_stat1:
                st.metric("編集前の壁セグメント数", result['json_data']['metadata']['total_walls'])
            with col_stat2:
                st.metric(
                    "編集後の壁セグメント数", 
                    result['updated_json']['metadata']['total_walls'],
                    delta=result['updated_json']['metadata']['total_walls'] - result['json_data']['metadata']['total_walls']
                )
            
            # デバッグログを表示（rerun後も表示される）
            if 'debug_log' in result and result['debug_log']:
                with st.expander("🔍 デバッグログ（詳細情報）", expanded=True):
                    for log_entry in result['debug_log']:
                        st.text(log_entry)
            
            # セッションステート更新の確認
            st.divider()
            col_save, col_discard = st.columns(2)
            with col_save:
                if st.button("💾 この結果を保存して続行", type="primary"):
                    # JSON・画像を更新
                    st.session_state.json_bytes = result['temp_json_path'].read_bytes()
                    st.session_state.json_name = "walls_3d_edited.json"
                    st.session_state.viz_bytes = result['temp_viz_path'].read_bytes()
                    
                    # 3DビューアHTMLも更新
                    st.session_state.viewer_html_bytes = result['viewer_html_bytes']
                    st.session_state.viewer_html_name = result['temp_viewer_path'].name

                    # 3D表示を開く
                    st.session_state.open_3d_expander = True

                    # 状態を完全にクリア
                    st.session_state.rect_coords = []
                    st.session_state.rect_coords_list = []
                    st.session_state.last_click = None
                    st.session_state.reset_flag = False
                    st.session_state.merge_result = None
                    
                    st.success("✅ 保存しました。さらに編集を続けることができます。")
                    time.sleep(0.5)
                    st.rerun()
            with col_discard:
                if st.button("❌ この結果を破棄"):
                    # 元のJSON・画像を復元
                    original_json_data = result['json_data']
                    original_viz_bytes = result['original_viz_bytes']
                    
                    # JSONを一時ファイルに書き戻す
                    temp_json_path = Path(st.session_state.out_dir) / "walls_3d_edited.json"
                    with open(temp_json_path, 'w', encoding='utf-8') as f:
                        json.dump(original_json_data, f, indent=2, ensure_ascii=False)
                    
                    # セッション状態を元に戻す
                    st.session_state.json_bytes = temp_json_path.read_bytes()
                    st.session_state.viz_bytes = original_viz_bytes
                    
                    # 状態をクリア
                    st.session_state.rect_coords = []
                    st.session_state.rect_coords_list = []
                    st.session_state.last_click = None
                    st.session_state.reset_flag = False
                    st.session_state.merge_result = None
                    st.info("✅ 編集を破棄して元に戻しました。")
                    st.rerun()
        else:
            # 編集結果がない場合のみ、編集UIを表示
            
            # 可視化画像を読み込み
            if st.session_state.viz_bytes:
                viz_img = Image.open(io.BytesIO(st.session_state.viz_bytes))
                
                # 選択範囲を描画した画像を作成
                import cv2
                display_img_array = np.array(viz_img.copy())
                
                # 線を結合モード・窓追加モード・線削除モード・スケール校正モード：選択された壁をハイライト表示
                selected_walls_to_highlight = []
                if edit_mode == "線を結合" and len(st.session_state.selected_walls_for_merge) > 0:
                    selected_walls_to_highlight = st.session_state.selected_walls_for_merge
                elif edit_mode == "窓を追加" and len(st.session_state.selected_walls_for_window) > 0:
                    selected_walls_to_highlight = st.session_state.selected_walls_for_window
                elif edit_mode == "線を削除" and len(st.session_state.selected_walls_for_delete) > 0:
                    selected_walls_to_highlight = st.session_state.selected_walls_for_delete
                elif edit_mode == "スケール校正" and st.session_state.selected_wall_for_calibration:
                    selected_walls_to_highlight = [st.session_state.selected_wall_for_calibration]
                
                if len(selected_walls_to_highlight) > 0:
                    try:
                        json_data_highlight = json.loads(st.session_state.json_bytes.decode("utf-8"))
                        walls_highlight = json_data_highlight.get('walls', [])
                        
                        all_x_highlight = [w['start'][0] for w in walls_highlight] + [w['end'][0] for w in walls_highlight]
                        all_y_highlight = [w['start'][1] for w in walls_highlight] + [w['end'][1] for w in walls_highlight]
                        min_x_highlight = min(all_x_highlight)
                        min_y_highlight = min(all_y_highlight)
                        max_x_highlight = max(all_x_highlight)
                        max_y_highlight = max(all_y_highlight)
                        
                        scale_highlight = int(st.session_state.viz_scale)
                        margin_highlight = 50
                        img_height_highlight = viz_img.height
                        
                        # 線を結合モード・窓追加モードで2本以上選択された場合：ギャップ部分のみを赤線で表示
                        if edit_mode == "線を結合" and len(selected_walls_to_highlight) >= 1:
                            # 線を結合モード：2本ずつペアでギャップを表示し、番号を振る
                            # 奇数本選択時は最後の1本を単独で表示
                            merge_pairs = []
                            for i in range(0, len(selected_walls_to_highlight), 2):
                                if i + 1 < len(selected_walls_to_highlight):
                                    merge_pairs.append((selected_walls_to_highlight[i], selected_walls_to_highlight[i + 1]))
                            
                            # ペアになっている結合を表示
                            for pair_idx, (wall1, wall2) in enumerate(merge_pairs):
                                try:
                                    # 2つの壁の4つの端点から最も近い組み合わせを見つける
                                    endpoints1 = [wall1['start'], wall1['end']]
                                    endpoints2 = [wall2['start'], wall2['end']]
                                    
                                    min_dist = float('inf')
                                    closest_p1 = None
                                    closest_p2 = None
                                    
                                    for p1 in endpoints1:
                                        for p2 in endpoints2:
                                            dist = _calc_distance(p1, p2)
                                            if dist < min_dist:
                                                min_dist = dist
                                                closest_p1 = p1
                                                closest_p2 = p2
                                    
                                    # 最も近い端点同士を赤線で結び、番号を表示
                                    if closest_p1 and closest_p2:
                                        gap_start_px_x = int((closest_p1[0] - min_x_highlight) * scale_highlight) + margin_highlight
                                        gap_start_px_y = img_height_highlight - (int((closest_p1[1] - min_y_highlight) * scale_highlight) + margin_highlight)
                                        gap_end_px_x = int((closest_p2[0] - min_x_highlight) * scale_highlight) + margin_highlight
                                        gap_end_px_y = img_height_highlight - (int((closest_p2[1] - min_y_highlight) * scale_highlight) + margin_highlight)
                                        
                                        # ギャップ部分を赤線で描画（太さ6）
                                        cv2.line(display_img_array, (gap_start_px_x, gap_start_px_y), (gap_end_px_x, gap_end_px_y), (0, 0, 255), 6)
                                        
                                        # ギャップの中心に結合番号を表示（薄いオレンジ背景の四角で囲む）
                                        center_x = (gap_start_px_x + gap_end_px_x) // 2
                                        center_y = (gap_start_px_y + gap_end_px_y) // 2
                                        merge_num = pair_idx + 1
                                        text = f"{merge_num}"
                                        text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.2, 2)[0]
                                        text_x = center_x - text_size[0] // 2
                                        text_y = center_y + text_size[1] // 2
                                        
                                        # 薄いオレンジ背景の四角形を描画 (BGR: 180, 220, 255 = 薄いオレンジ)
                                        cv2.rectangle(display_img_array,
                                                    (text_x - 5, text_y - text_size[1] - 5),
                                                    (text_x + text_size[0] + 5, text_y + 5),
                                                    (180, 220, 255), -1)
                                        # 黒枠を描画
                                        cv2.rectangle(display_img_array,
                                                    (text_x - 5, text_y - text_size[1] - 5),
                                                    (text_x + text_size[0] + 5, text_y + 5),
                                                    (0, 0, 0), 2)
                                        # 番号を描画（黒文字）
                                        cv2.putText(display_img_array, text, (text_x, text_y),
                                                   cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
                                except Exception:
                                    pass
                            
                            # 奇数本選択時：最後の1本を単独で表示（線結合と同じスタイルで「1」表示）
                            if len(selected_walls_to_highlight) % 2 == 1:
                                last_wall = selected_walls_to_highlight[-1]
                                
                                try:
                                    start_m = last_wall['start']
                                    end_m = last_wall['end']
                                    
                                    # メートル→ピクセル変換
                                    start_px_x = int((start_m[0] - min_x_highlight) * scale_highlight) + margin_highlight
                                    start_px_y = img_height_highlight - (int((start_m[1] - min_y_highlight) * scale_highlight) + margin_highlight)
                                    end_px_x = int((end_m[0] - min_x_highlight) * scale_highlight) + margin_highlight
                                    end_px_y = img_height_highlight - (int((end_m[1] - min_y_highlight) * scale_highlight) + margin_highlight)
                                    
                                    # 壁線を青色でハイライト表示（太さ6）
                                    cv2.line(display_img_array, (start_px_x, start_px_y), (end_px_x, end_px_y), (255, 0, 0), 6)
                                    
                                    # 壁線の中心に「1」を四角で囲んで表示（線結合と同じスタイル）
                                    mid_x = (start_px_x + end_px_x) // 2
                                    mid_y = (start_px_y + end_px_y) // 2
                                    text = "1"
                                    text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)[0]
                                    text_x = mid_x - text_size[0] // 2
                                    text_y = mid_y + text_size[1] // 2
                                    
                                    # 白背景の四角形を描画
                                    cv2.rectangle(display_img_array,
                                                (text_x - 5, text_y - text_size[1] - 5),
                                                (text_x + text_size[0] + 5, text_y + 5),
                                                (255, 255, 255), -1)
                                    # 黒枠を描画
                                    cv2.rectangle(display_img_array,
                                                (text_x - 5, text_y - text_size[1] - 5),
                                                (text_x + text_size[0] + 5, text_y + 5),
                                                (0, 0, 0), 2)
                                    # 番号を描画（黒文字）
                                    cv2.putText(display_img_array, text, (text_x, text_y),
                                               cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
                                except Exception as e:
                                    print(f"[ERROR] 奇数本描画エラー: {e}")
                                    pass
                        elif edit_mode == "窓を追加" and len(selected_walls_to_highlight) >= 1:
                            # 窓追加モード：2本ずつペアでギャップを表示し、番号を振る
                            # 奇数本選択時は最後の1本を単独で表示
                            window_pairs = []
                            for i in range(0, len(selected_walls_to_highlight), 2):
                                if i + 1 < len(selected_walls_to_highlight):
                                    window_pairs.append((selected_walls_to_highlight[i], selected_walls_to_highlight[i + 1]))
                            
                            # ペアになっている窓を表示
                            for pair_idx, (wall1, wall2) in enumerate(window_pairs):
                                try:
                                    # 2つの壁の4つの端点から最も近い組み合わせを見つける
                                    endpoints1 = [wall1['start'], wall1['end']]
                                    endpoints2 = [wall2['start'], wall2['end']]
                                    
                                    min_dist = float('inf')
                                    closest_p1 = None
                                    closest_p2 = None
                                    
                                    for p1 in endpoints1:
                                        for p2 in endpoints2:
                                            dist = _calc_distance(p1, p2)
                                            if dist < min_dist:
                                                min_dist = dist
                                                closest_p1 = p1
                                                closest_p2 = p2
                                    
                                    # 最も近い端点同士を赤線で結び、番号を表示
                                    if closest_p1 and closest_p2:
                                        gap_start_px_x = int((closest_p1[0] - min_x_highlight) * scale_highlight) + margin_highlight
                                        gap_start_px_y = img_height_highlight - (int((closest_p1[1] - min_y_highlight) * scale_highlight) + margin_highlight)
                                        gap_end_px_x = int((closest_p2[0] - min_x_highlight) * scale_highlight) + margin_highlight
                                        gap_end_px_y = img_height_highlight - (int((closest_p2[1] - min_y_highlight) * scale_highlight) + margin_highlight)
                                        
                                        # ギャップ部分を赤線で描画（太さ6）
                                        cv2.line(display_img_array, (gap_start_px_x, gap_start_px_y), (gap_end_px_x, gap_end_px_y), (0, 0, 255), 6)
                                        
                                        # ギャップの中心に窓番号を四角で囲んで表示（薄い水色背景）
                                        center_x = (gap_start_px_x + gap_end_px_x) // 2
                                        center_y = (gap_start_px_y + gap_end_px_y) // 2
                                        window_num = pair_idx + 1
                                        text = f"{window_num}"
                                        text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.2, 2)[0]
                                        text_x = center_x - text_size[0] // 2
                                        text_y = center_y + text_size[1] // 2
                                        
                                        # 薄い水色背景の四角形を描画 (BGR: 255, 200, 150 = 薄い水色)
                                        cv2.rectangle(display_img_array,
                                                    (text_x - 5, text_y - text_size[1] - 5),
                                                    (text_x + text_size[0] + 5, text_y + 5),
                                                    (255, 200, 150), -1)
                                        # 黒枠を描画
                                        cv2.rectangle(display_img_array,
                                                    (text_x - 5, text_y - text_size[1] - 5),
                                                    (text_x + text_size[0] + 5, text_y + 5),
                                                    (0, 0, 0), 2)
                                        # 番号を描画（黒文字）
                                        cv2.putText(display_img_array, text, (text_x, text_y),
                                                   cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
                                except Exception:
                                    pass
                            
                            # 奇数本選択時：最後の1本を単独で表示（線結合と同じスタイルで「1」表示）
                            if len(selected_walls_to_highlight) % 2 == 1:
                                last_wall = selected_walls_to_highlight[-1]
                                
                                try:
                                    start_m = last_wall['start']
                                    end_m = last_wall['end']
                                    
                                    # メートル→ピクセル変換
                                    start_px_x = int((start_m[0] - min_x_highlight) * scale_highlight) + margin_highlight
                                    start_px_y = img_height_highlight - (int((start_m[1] - min_y_highlight) * scale_highlight) + margin_highlight)
                                    end_px_x = int((end_m[0] - min_x_highlight) * scale_highlight) + margin_highlight
                                    end_px_y = img_height_highlight - (int((end_m[1] - min_y_highlight) * scale_highlight) + margin_highlight)
                                    
                                    # 壁線を青色でハイライト表示（太さ6）
                                    cv2.line(display_img_array, (start_px_x, start_px_y), (end_px_x, end_px_y), (255, 0, 0), 6)
                                    
                                    # 壁線の中心に「1」を四角で囲んで表示（線結合と同じスタイル）
                                    mid_x = (start_px_x + end_px_x) // 2
                                    mid_y = (start_px_y + end_px_y) // 2
                                    text = "1"
                                    text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)[0]
                                    text_x = mid_x - text_size[0] // 2
                                    text_y = mid_y + text_size[1] // 2
                                    
                                    # 白背景の四角形を描画
                                    cv2.rectangle(display_img_array,
                                                (text_x - 5, text_y - text_size[1] - 5),
                                                (text_x + text_size[0] + 5, text_y + 5),
                                                (255, 255, 255), -1)
                                    # 黒枠を描画
                                    cv2.rectangle(display_img_array,
                                                (text_x - 5, text_y - text_size[1] - 5),
                                                (text_x + text_size[0] + 5, text_y + 5),
                                                (0, 0, 0), 2)
                                    # 番号を描画（黒文字）
                                    cv2.putText(display_img_array, text, (text_x, text_y),
                                               cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
                                except Exception as e:
                                    print(f"[ERROR] 奇数本描画エラー: {e}")
                                    pass
                        elif edit_mode == "スケール校正" and len(selected_walls_to_highlight) > 0:
                            # スケール校正モード：選択された1本の壁を赤色でハイライト
                            wall = selected_walls_to_highlight[0]
                            try:
                                start_m = wall['start']
                                end_m = wall['end']
                                
                                # メートル→ピクセル変換
                                start_px_x = int((start_m[0] - min_x_highlight) * scale_highlight) + margin_highlight
                                start_px_y = img_height_highlight - (int((start_m[1] - min_y_highlight) * scale_highlight) + margin_highlight)
                                end_px_x = int((end_m[0] - min_x_highlight) * scale_highlight) + margin_highlight
                                end_px_y = img_height_highlight - (int((end_m[1] - min_y_highlight) * scale_highlight) + margin_highlight)
                                
                                # 壁線を赤色でハイライト表示（太さ6）
                                cv2.line(display_img_array, (start_px_x, start_px_y), (end_px_x, end_px_y), (0, 0, 255), 6)
                            except Exception as e:
                                print(f"[ERROR] スケール校正モード描画エラー: {e}")
                                pass
                        elif edit_mode != "窓を追加":
                            # その他のモード（線削除、線を結合）のみ：従来通り
                            # 線を削除：すべて赤
                            # 線を結合：青→緑
                            if edit_mode == "線を削除":
                                colors = [(0, 0, 255)] * 20  # 赤色で統一（BGR形式）
                            else:
                                colors = [(255, 0, 0), (0, 255, 0)]  # 1本目：青、2本目：緑（BGR形式）
                            
                            for idx, wall in enumerate(selected_walls_to_highlight):
                                start_m = wall['start']
                                end_m = wall['end']
                                
                                # メートル→ピクセル変換
                                start_px_x = int((start_m[0] - min_x_highlight) * scale_highlight) + margin_highlight
                                start_px_y = img_height_highlight - (int((start_m[1] - min_y_highlight) * scale_highlight) + margin_highlight)
                                end_px_x = int((end_m[0] - min_x_highlight) * scale_highlight) + margin_highlight
                                end_px_y = img_height_highlight - (int((end_m[1] - min_y_highlight) * scale_highlight) + margin_highlight)
                                
                                # 選択された壁を太く描画
                                cv2.line(display_img_array, (start_px_x, start_px_y), (end_px_x, end_px_y), colors[idx], 6)
                                
                                # 壁の中心に番号を表示
                                mid_x = (start_px_x + end_px_x) // 2
                                mid_y = (start_px_y + end_px_y) // 2
                                text = f"{idx+1}"
                                text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)[0]
                                text_x = mid_x - text_size[0] // 2
                                text_y = mid_y + text_size[1] // 2
                                
                                # 白背景の四角形を描画
                                cv2.rectangle(display_img_array, 
                                            (text_x - 5, text_y - text_size[1] - 5),
                                            (text_x + text_size[0] + 5, text_y + 5),
                                            (255, 255, 255), -1)
                                # 黒枠を描画
                                cv2.rectangle(display_img_array, 
                                            (text_x - 5, text_y - text_size[1] - 5),
                                            (text_x + text_size[0] + 5, text_y + 5),
                                            (0, 0, 0), 2)
                                # 番号を描画（黒文字）
                                cv2.putText(display_img_array, text, (text_x, text_y), 
                                          cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
                    except Exception as ex:
                        print(f"[ERROR] ハイライト描画の外側エラー: {ex}")
                        import traceback
                        traceback.print_exc()
                        pass  # エラー時は無視
                
                # 確定済みの四角形を描画（異なる色で）
                for idx, (p1, p2) in enumerate(st.session_state.rect_coords_list):
                    color = RECT_COLORS[idx % len(RECT_COLORS)]
                    x1, y1 = min(p1[0], p2[0]), min(p1[1], p2[1])
                    x2, y2 = max(p1[0], p2[0]), max(p1[1], p2[1])
                    
                    # 線削除モードの場合は四角形内の壁を色変更
                    if edit_mode == "線を削除":
                        try:
                            json_data_del = json.loads(st.session_state.json_bytes.decode("utf-8"))
                            walls_del = json_data_del.get('walls', [])
                            
                            all_x_del = [w['start'][0] for w in walls_del] + [w['end'][0] for w in walls_del]
                            all_y_del = [w['start'][1] for w in walls_del] + [w['end'][1] for w in walls_del]
                            min_x_del = min(all_x_del)
                            min_y_del = min(all_y_del)
                            max_x_del = max(all_x_del)
                            max_y_del = max(all_y_del)
                            
                            scale_del = int(st.session_state.viz_scale)
                            margin_del = 50
                            img_height_del = viz_img.height
                            
                            rect_del = {
                                'left': x1,
                                'top': y1,
                                'width': x2 - x1,
                                'height': y2 - y1
                            }
                            
                            walls_in_rect_del = _filter_walls_strictly_in_rect(
                                walls_del, rect_del, scale_del, margin_del,
                                img_height_del, min_x_del, min_y_del, max_x_del, max_y_del
                            )
                            
                            # 削除対象の壁を赤色で太く描画
                            if len(walls_in_rect_del) > 0:
                                for wall in walls_in_rect_del:
                                    start_m = wall['start']
                                    end_m = wall['end']
                                    
                                    # メートル→ピクセル変換
                                    start_px_x = int((start_m[0] - min_x_del) * scale_del) + margin_del
                                    start_px_y = img_height_del - (int((start_m[1] - min_y_del) * scale_del) + margin_del)
                                    end_px_x = int((end_m[0] - min_x_del) * scale_del) + margin_del
                                    end_px_y = img_height_del - (int((end_m[1] - min_y_del) * scale_del) + margin_del)
                                    
                                    # 赤色で太い線を描画（削除対象）
                                    cv2.line(display_img_array, (start_px_x, start_px_y), (end_px_x, end_px_y), (0, 0, 255), 8)
                            else:
                                # 壁が見つからない場合は四角形を表示
                                overlay = display_img_array.copy()
                                cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
                                cv2.addWeighted(overlay, 0.25, display_img_array, 0.75, 0, display_img_array)
                                cv2.rectangle(display_img_array, (x1, y1), (x2, y2), color, 3)
                                cv2.putText(display_img_array, f"{idx+1}", (x1+5, y1+25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                        except Exception:
                            # エラー時は四角形を表示
                            overlay = display_img_array.copy()
                            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
                            cv2.addWeighted(overlay, 0.25, display_img_array, 0.75, 0, display_img_array)
                            cv2.rectangle(display_img_array, (x1, y1), (x2, y2), color, 3)
                            cv2.putText(display_img_array, f"{idx+1}", (x1+5, y1+25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                    # 窓追加モードまたは線を結合モードの場合は四角形ではなく追加予定の壁を線で表示
                    elif edit_mode == "窓を追加" or edit_mode == "線を結合":
                        try:
                            json_data_confirmed = json.loads(st.session_state.json_bytes.decode("utf-8"))
                            walls_confirmed = json_data_confirmed.get('walls', [])
                            
                            all_x_confirmed = [w['start'][0] for w in walls_confirmed] + [w['end'][0] for w in walls_confirmed]
                            all_y_confirmed = [w['start'][1] for w in walls_confirmed] + [w['end'][1] for w in walls_confirmed]
                            min_x_confirmed = min(all_x_confirmed)
                            min_y_confirmed = min(all_y_confirmed)
                            max_x_confirmed = max(all_x_confirmed)
                            max_y_confirmed = max(all_y_confirmed)
                            
                            scale_confirmed = int(st.session_state.viz_scale)
                            margin_confirmed = 50
                            img_height_confirmed = viz_img.height
                            
                            rect_confirmed = {
                                'left': x1,
                                'top': y1,
                                'width': x2 - x1,
                                'height': y2 - y1
                            }
                            
                            # 窓追加モードおよび線を結合モードでは端点/交差ベースで検出（端点だけ囲む操作に対応）
                            if edit_mode in ("窓を追加", "線を結合"):
                                walls_in_rect_confirmed = _filter_walls_by_endpoints_in_rect(
                                    walls_confirmed, rect_confirmed, scale_confirmed, margin_confirmed,
                                    img_height_confirmed, min_x_confirmed, min_y_confirmed, max_x_confirmed, max_y_confirmed,
                                    tolerance=0, debug=False
                                )
                            else:
                                walls_in_rect_confirmed = _filter_walls_strictly_in_rect(
                                    walls_confirmed, rect_confirmed, scale_confirmed, margin_confirmed,
                                    img_height_confirmed, min_x_confirmed, min_y_confirmed, max_x_confirmed, max_y_confirmed
                                )

                            # プレビューと同じく、端点が重なって余分な線が含まれる場合は縦横判定して最適な2本を選択
                            try:
                                if len(walls_in_rect_confirmed) >= 3:
                                    # 3本以上：縦横を分類して最も近い平行な壁のペアを選ぶ
                                    best_pair = _select_best_wall_pair_from_4(walls_in_rect_confirmed)
                                    walls_in_rect_confirmed = best_pair if best_pair else walls_in_rect_confirmed[:2]
                                else:
                                    # 2本以下の場合はそのまま使用
                                    walls_in_rect_confirmed = walls_in_rect_confirmed
                            except Exception:
                                pass

                            
                            if len(walls_in_rect_confirmed) == 2:
                                params = st.session_state.get('window_execution_params', {})
                                window_height_confirmed = params.get('window_height', 1.2)
                                base_height_confirmed = params.get('base_height', 0.9)
                                
                                wall1_confirmed = walls_in_rect_confirmed[0]
                                wall2_confirmed = walls_in_rect_confirmed[1]
                                
                                endpoints_confirmed = [
                                    (wall1_confirmed['start'], wall2_confirmed['start']),
                                    (wall1_confirmed['start'], wall2_confirmed['end']),
                                    (wall1_confirmed['end'], wall2_confirmed['start']),
                                    (wall1_confirmed['end'], wall2_confirmed['end']),
                                ]
                                
                                min_dist_confirmed = float('inf')
                                window_start_confirmed = None
                                window_end_confirmed = None
                                
                                for p1_win, p2_win in endpoints_confirmed:
                                    dist_win = math.sqrt((p1_win[0] - p2_win[0])**2 + (p1_win[1] - p2_win[1])**2)
                                    if dist_win < min_dist_confirmed:
                                        min_dist_confirmed = dist_win
                                        window_start_confirmed = p1_win
                                        window_end_confirmed = p2_win
                                
                                if window_start_confirmed and window_end_confirmed:
                                    start_px = [
                                        int((window_start_confirmed[0] - min_x_confirmed) * scale_confirmed) + margin_confirmed,
                                        img_height_confirmed - (int((window_start_confirmed[1] - min_y_confirmed) * scale_confirmed) + margin_confirmed)
                                    ]
                                    end_px = [
                                        int((window_end_confirmed[0] - min_x_confirmed) * scale_confirmed) + margin_confirmed,
                                        img_height_confirmed - (int((window_end_confirmed[1] - min_y_confirmed) * scale_confirmed) + margin_confirmed)
                                    ]
                                    
                                    # 線を結合モードは青色、窓追加モードは赤色
                                    line_color = (255, 0, 0) if edit_mode == "線を結合" else (0, 0, 255)  # BGR形式
                                    cv2.line(display_img_array, tuple(start_px), tuple(end_px), line_color, 5)
                                    cv2.circle(display_img_array, tuple(start_px), 8, line_color, -1)
                                    cv2.circle(display_img_array, tuple(end_px), 8, line_color, -1)
                                    
                                    # 番号を描画（線の上側、白背景で視認性向上）
                                    mid_x = (start_px[0] + end_px[0]) // 2
                                    mid_y = (start_px[1] + end_px[1]) // 2
                                    text = f"{idx+1}"
                                    text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)[0]
                                    text_x = mid_x - text_size[0] // 2
                                    text_y = mid_y - 20  # 線の上側に配置
                                    # 白背景の四角形を描画
                                    cv2.rectangle(display_img_array, 
                                                (text_x - 5, text_y - text_size[1] - 5),
                                                (text_x + text_size[0] + 5, text_y + 5),
                                                (255, 255, 255), -1)
                                    # 黒枠を描画
                                    cv2.rectangle(display_img_array, 
                                                (text_x - 5, text_y - text_size[1] - 5),
                                                (text_x + text_size[0] + 5, text_y + 5),
                                                (0, 0, 0), 2)
                                    # 番号を描画（黒文字）
                                    cv2.putText(display_img_array, text, (text_x, text_y), 
                                              cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
                            else:
                                # 2本検出できない場合は四角形を表示
                                overlay = display_img_array.copy()
                                cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
                                cv2.addWeighted(overlay, 0.25, display_img_array, 0.75, 0, display_img_array)
                                cv2.rectangle(display_img_array, (x1, y1), (x2, y2), color, 3)
                                cv2.putText(display_img_array, f"{idx+1}", (x1+5, y1+25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                        except Exception:
                            # エラー時は通常の四角形表示
                            overlay = display_img_array.copy()
                            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
                            cv2.addWeighted(overlay, 0.25, display_img_array, 0.75, 0, display_img_array)
                            cv2.rectangle(display_img_array, (x1, y1), (x2, y2), color, 3)
                            cv2.putText(display_img_array, f"{idx+1}", (x1+5, y1+25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                    elif edit_mode == "階段を配置":
                        # 階段追加モード：青色の矩形で階段エリアを表示
                        stair_color = (255, 0, 0)  # BGR形式で青色
                        # 半透明の四角形を描画
                        overlay = display_img_array.copy()
                        cv2.rectangle(overlay, (x1, y1), (x2, y2), stair_color, -1)
                        cv2.addWeighted(overlay, 0.3, display_img_array, 0.7, 0, display_img_array)
                        # 四角形の枠線を描画（太めの青線）
                        cv2.rectangle(display_img_array, (x1, y1), (x2, y2), stair_color, 5)
                        # 番号と階段アイコンを描画
                        text = f"🪜 {idx+1}"
                        cv2.putText(display_img_array, f"Stair {idx+1}", (x1+5, y1+30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 3)
                        cv2.putText(display_img_array, f"Stair {idx+1}", (x1+5, y1+30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, stair_color, 2)
                    else:
                        # 窓追加モード・線を結合モード以外は通常の四角形表示
                        # 半透明の四角形を描画
                        overlay = display_img_array.copy()
                        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
                        cv2.addWeighted(overlay, 0.25, display_img_array, 0.75, 0, display_img_array)
                        # 四角形の枠線を描画
                        cv2.rectangle(display_img_array, (x1, y1), (x2, y2), color, 3)
                        # 番号を描画
                        cv2.putText(display_img_array, f"{idx+1}", (x1+5, y1+25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                
                # 現在選択中の四角形を描画（赤色で表示）
                if len(st.session_state.rect_coords) == 1:
                    # 1点目を赤い円で表示
                    red_color = (0, 0, 255)  # BGR形式で赤色
                    cv2.circle(display_img_array, st.session_state.rect_coords[0], 12, red_color, -1)  # 塗りつぶし円
                    cv2.circle(display_img_array, st.session_state.rect_coords[0], 15, (255, 255, 255), 2)  # 白枠
                elif len(st.session_state.rect_coords) == 2:
                    # 2点を赤い円で表示し、四角形も描画
                    red_color = (0, 0, 255)  # BGR形式で赤色
                    p1, p2 = st.session_state.rect_coords
                    x1, y1 = min(p1[0], p2[0]), min(p1[1], p2[1])
                    x2, y2 = max(p1[0], p2[0]), max(p1[1], p2[1])
                    # 半透明の四角形を描画
                    overlay = display_img_array.copy()
                    cv2.rectangle(overlay, (x1, y1), (x2, y2), red_color, -1)
                    cv2.addWeighted(overlay, 0.3, display_img_array, 0.7, 0, display_img_array)
                    # 四角形の枠線を描画
                    cv2.rectangle(display_img_array, (x1, y1), (x2, y2), red_color, 3)
                    # 両端に赤い円を表示
                    cv2.circle(display_img_array, p1, 12, red_color, -1)
                    cv2.circle(display_img_array, p1, 15, (255, 255, 255), 2)
                    cv2.circle(display_img_array, p2, 12, red_color, -1)
                    cv2.circle(display_img_array, p2, 15, (255, 255, 255), 2)
                    
                    # 窓追加モードまたは線を結合モードの場合、追加予定の壁を線で表示
                    if edit_mode == "窓を追加" or edit_mode == "線を結合":
                        try:
                            json_data_preview = json.loads(st.session_state.json_bytes.decode("utf-8"))
                            walls_preview = json_data_preview.get('walls', [])
                            
                            # 可視化画像のパラメータを取得
                            all_x_preview = [w['start'][0] for w in walls_preview] + [w['end'][0] for w in walls_preview]
                            all_y_preview = [w['start'][1] for w in walls_preview] + [w['end'][1] for w in walls_preview]
                            min_x_preview = min(all_x_preview)
                            min_y_preview = min(all_y_preview)
                            max_x_preview = max(all_x_preview)
                            max_y_preview = max(all_y_preview)
                            
                            scale_preview = int(st.session_state.viz_scale)
                            margin_preview = 50
                            img_height_preview = viz_img.height
                            
                            rect_preview = {
                                'left': x1,
                                'top': y1,
                                'width': x2 - x1,
                                'height': y2 - y1
                            }
                            
                            # 範囲内の壁を検出（窓追加/線を結合では端点/交差ベース）
                            if edit_mode in ("窓を追加", "線を結合"):
                                walls_in_rect_preview = _filter_walls_by_endpoints_in_rect(
                                    walls_preview, rect_preview, scale_preview, margin_preview,
                                    img_height_preview, min_x_preview, min_y_preview, max_x_preview, max_y_preview,
                                    tolerance=0, debug=False
                                )
                            else:
                                walls_in_rect_preview = _filter_walls_strictly_in_rect(
                                    walls_preview, rect_preview, scale_preview, margin_preview, 
                                    img_height_preview, min_x_preview, min_y_preview, max_x_preview, max_y_preview
                                )

                            # 追加表示用に、縦横を判定して最適な線を選択（プレビュー整合性）
                            try:
                                if len(walls_in_rect_preview) >= 3:
                                    # 3本以上：縦横を分類して最も近い平行な壁のペアを選ぶ
                                    best_pair = _select_best_wall_pair_from_4(walls_in_rect_preview)
                                    walls_in_rect_filtered = best_pair if best_pair else walls_in_rect_preview[:2]
                                else:
                                    # 2本以下の場合はそのまま使用
                                    walls_in_rect_filtered = walls_in_rect_preview
                            except Exception:
                                walls_in_rect_filtered = walls_in_rect_preview

                            # プレビュー時の詳細デバッグ出力（2点目選択直後に表示）
                            try:
                                # プレビュー時の内部マッピングは表示しない（ログのみ残す）
                                preview_debug = []
                                for w in walls_preview:
                                    x1w = int((w['start'][0] - min_x_preview) * scale_preview) + margin_preview
                                    y1w = img_height_preview - (int((w['start'][1] - min_y_preview) * scale_preview) + margin_preview)
                                    x2w = int((w['end'][0] - min_x_preview) * scale_preview) + margin_preview
                                    y2w = img_height_preview - (int((w['end'][1] - min_y_preview) * scale_preview) + margin_preview)
                                    in_rect = (
                                        (rect_preview['left'] <= x1w <= rect_preview['left'] + rect_preview['width'] and rect_preview['top'] <= y1w <= rect_preview['top'] + rect_preview['height']) or
                                        (rect_preview['left'] <= x2w <= rect_preview['left'] + rect_preview['width'] and rect_preview['top'] <= y2w <= rect_preview['top'] + rect_preview['height']) or
                                        _line_intersects_rect(x1w, y1w, x2w, y2w, rect_preview, tolerance=20)
                                    )
                                    preview_debug.append({'id': w.get('id'), 'start_px': (x1w, y1w), 'end_px': (x2w, y2w), 'in_rect': in_rect})
                                try:
                                    append_debug(f"Preview mapping: detected={[d['id'] for d in preview_debug if d.get('in_rect')]}, total_checked={len(preview_debug)}")
                                except Exception:
                                    pass
                            except Exception:
                                pass

                            # 検出が2本以上ある場合、追加予定の線を描画
                            if len(walls_in_rect_filtered) >= 2:
                                # まず窓パラメータを取得（表示用）
                                params = st.session_state.get('window_execution_params', {})
                                window_height_preview = params.get('window_height', 1.2)
                                base_height_preview = params.get('base_height', 0.9)
                                room_height_preview = params.get('room_height', 2.4)

                                # 2本より多い場合は四角形の主方向に沿って最も離れた2本を選ぶ
                                selected_walls = None
                                try:
                                    rect_w = rect_preview.get('width', 0)
                                    rect_h = rect_preview.get('height', 0)
                                    if len(walls_in_rect_filtered) == 2:
                                        selected_walls = [walls_in_rect_filtered[0], walls_in_rect_filtered[1]]
                                    else:
                                        if rect_w > rect_h:
                                            walls_by_x = sorted(walls_in_rect_filtered, key=lambda w: min(w['start'][0], w['end'][0]))
                                            selected_walls = [walls_by_x[0], walls_by_x[-1]]
                                        else:
                                            walls_by_y = sorted(walls_in_rect_filtered, key=lambda w: min(w['start'][1], w['end'][1]))
                                            selected_walls = [walls_by_y[0], walls_by_y[-1]]
                                except Exception:
                                    selected_walls = walls_in_rect_filtered[:2]

                                # 選ばれた2本から最短端点対を探す
                                wall1_preview = selected_walls[0]
                                wall2_preview = selected_walls[1]
                                endpoints_preview = [
                                    (wall1_preview['start'], wall2_preview['start']),
                                    (wall1_preview['start'], wall2_preview['end']),
                                    (wall1_preview['end'], wall2_preview['start']),
                                    (wall1_preview['end'], wall2_preview['end']),
                                ]

                                min_dist_preview = float('inf')
                                window_start_preview = None
                                window_end_preview = None
                                for p1_win, p2_win in endpoints_preview:
                                    dist_win = math.sqrt((p1_win[0] - p2_win[0])**2 + (p1_win[1] - p2_win[1])**2)
                                    if dist_win < min_dist_preview:
                                        min_dist_preview = dist_win
                                        window_start_preview = p1_win
                                        window_end_preview = p2_win

                                # メートル座標をピクセル座標に変換して線を描画
                                if window_start_preview and window_end_preview:
                                    start_px = [
                                        int((window_start_preview[0] - min_x_preview) * scale_preview) + margin_preview,
                                        img_height_preview - (int((window_start_preview[1] - min_y_preview) * scale_preview) + margin_preview)
                                    ]
                                    end_px = [
                                        int((window_end_preview[0] - min_x_preview) * scale_preview) + margin_preview,
                                        img_height_preview - (int((window_end_preview[1] - min_y_preview) * scale_preview) + margin_preview)
                                    ]

                                    # 線を結合モードは青色、窓追加モードは赤色で太い線を描画
                                    line_color = (255, 0, 0) if edit_mode == "線を結合" else (0, 0, 255)  # BGR形式
                                    cv2.line(display_img_array, tuple(start_px), tuple(end_px), line_color, 5)
                                    cv2.circle(display_img_array, tuple(start_px), 8, line_color, -1)
                                    cv2.circle(display_img_array, tuple(end_px), 8, line_color, -1)

                                    # プレビューで選択したペアをセッションに保存（実行時に優先利用）
                                    try:
                                        st.session_state['last_preview_pair'] = [wall1_preview.get('id'), wall2_preview.get('id')]
                                        st.session_state['last_preview_rect'] = rect_preview
                                        # フィルタ済みの検出IDリストも保存（デバッグ/実行整合用）
                                        try:
                                            st.session_state['last_preview_detected_ids'] = [w.get('id') for w in walls_in_rect_preview]
                                            st.session_state['last_preview_filtered_ids'] = [w.get('id') for w in walls_in_rect_filtered]
                                        except Exception:
                                            pass
                                    except Exception:
                                        pass

                                    # プレビュー用に番号も描画（確定リストに追加されていない未追加プレビュー）
                                    try:
                                        preview_idx = len(st.session_state.get('rect_coords_list', [])) + 1
                                        mid_x = (start_px[0] + end_px[0]) // 2
                                        mid_y = (start_px[1] + end_px[1]) // 2
                                        text = f"{preview_idx}"
                                        text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)[0]
                                        text_x = mid_x - text_size[0] // 2
                                        text_y = mid_y - 20
                                        cv2.rectangle(display_img_array,
                                                      (text_x - 5, text_y - text_size[1] - 5),
                                                      (text_x + text_size[0] + 5, text_y + 5),
                                                      (255, 255, 255), -1)
                                        cv2.rectangle(display_img_array,
                                                      (text_x - 5, text_y - text_size[1] - 5),
                                                      (text_x + text_size[0] + 5, text_y + 5),
                                                      (0, 0, 0), 2)
                                        cv2.putText(display_img_array, text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
                                    except Exception:
                                        pass
                        except Exception as e:
                            # プレビュー描画のエラーは無視（通常の四角形表示を続行）
                            pass
                
                display_img = Image.fromarray(display_img_array)
                display_img_resized, scale_ratio, _, _ = _prepare_display_from_pil(display_img, max_width=DISPLAY_IMAGE_WIDTH)
                
                # ズーム機能: 画像サイズを調整
                zoom_level = st.session_state.get('editor_zoom_level', 1.0)
                if zoom_level != 1.0:
                    w, h = display_img_resized.size
                    display_img_resized = display_img_resized.resize(
                        (int(w * zoom_level), int(h * zoom_level)),
                        Image.Resampling.LANCZOS
                    )
                
                # skip_click_processingフラグを画面描画時に無条件でクリア（フラグが残り続けるのを防ぐ）
                if st.session_state.get('skip_click_processing'):
                    st.session_state.skip_click_processing = False
                
                # UI表示：モード別
                if edit_mode == "線を結合":
                    # 線を結合モード：壁線クリック選択（2本ずつペアで複数結合可能）
                    num_selected = len(st.session_state.selected_walls_for_merge)
                    if num_selected == 0:
                        pass
                        #st.write("💡 結合したい壁線を1本目クリックしてください")
                    elif num_selected % 2 == 1:
                        merge_num = (num_selected // 2) + 1
                        #st.info(f"✅ **結合{merge_num}：1本目選択完了** → 2本目の壁線をクリックしてください")
                    else:
                        merge_count = num_selected // 2
                        #st.success(f"✅ **{merge_count}組の結合を選択完了**\n\n→ さらに結合を追加する場合は下の編集画面で次の壁線をクリック\n\n→ 確定する場合は下の「🔗 結合実行」ボタンをクリックしてください")
                        
                        # 結合実行ボタン（選択完了メッセージの直後、画像の前に表示）
                        st.markdown("---")
                        if st.button("🔗 結合実行", type="primary", key="btn_merge_exec_top"):
                            # 選択された壁をセッションに保存してから選択リストをクリア
                            st.session_state.merge_walls_to_process = list(st.session_state.selected_walls_for_merge)
                            st.session_state.selected_walls_for_merge = []
                            st.session_state.skip_click_processing = True  # クリック処理をスキップ
                            # 即座にrerunして選択状態をクリア（次のrerunで実際の処理を実行）
                            st.rerun()
                elif edit_mode == "窓を追加":
                    # 窓追加モード：壁線クリック選択（2本ずつペアで複数窓追加可能）
                    num_selected = len(st.session_state.selected_walls_for_window)
                    if num_selected == 0:
                        pass
                        #st.write("💡 窓を追加したい壁線(2本)をクリックしてください")
                    elif num_selected % 2 == 1:
                        window_num = (num_selected // 2) + 1
                        #st.info(f"✅ **窓{window_num}：1本目選択完了** → 2本目の壁線をクリックしてください")
                    else:
                        window_count = num_selected // 2
                        #st.success(f"✅ **{window_count}組の窓を選択完了**\n\n→ さらに窓を追加する場合は下の編集画面で次の壁線をクリック\n\n→ 確定する場合は下で窓パラメータを入力して「🪟 窓追加実行」ボタンをクリックしてください")
                        
                        # 窓パラメータ入力フォーム（選択完了メッセージの直後、画像の前に表示）
                        st.markdown("---")
                        st.markdown(f"### 🪟 窓のサイズを入力（{window_count}組）")
                        
                        # セッションステートに窓パラメータリストを初期化
                        if 'window_click_params_list' not in st.session_state:
                            st.session_state.window_click_params_list = []
                        
                        # 必要な数だけパラメータを確保
                        while len(st.session_state.window_click_params_list) < window_count:
                            st.session_state.window_click_params_list.append({
                                'model': 'J4415/JF4415',
                                'width_mm': 1200,
                                'height_mm': 1200,
                                'base_mm': 900
                            })
                        
                        # 各窓ごとに入力欄を表示
                        window_params_to_save = []
                        for window_idx in range(window_count):
                            st.markdown(f"#### 窓{window_idx + 1}")
                            col1, col2, col3 = st.columns(3)
                            
                            with col1:
                                # 現在の型番を取得
                                current_model = st.session_state.window_click_params_list[window_idx].get('model', 'J4415/JF4415')
                                
                                window_model = st.selectbox(
                                    f"窓{window_idx + 1}の型番(数字4桁)",
                                    list(WINDOW_CATALOG.keys()),
                                    index=list(WINDOW_CATALOG.keys()).index(current_model) if current_model in WINDOW_CATALOG.keys() else 0,
                                    help="窓の型番(数字4桁)を選択してください",
                                    key=f"window_model_click_{window_idx}"
                                )
                                
                                # 型番が変更された場合、カタログ値で更新してrerun
                                if window_model != current_model:
                                    st.session_state.window_click_params_list[window_idx]['model'] = window_model
                                    if window_model in WINDOW_CATALOG:
                                        catalog_entry = WINDOW_CATALOG[window_model]
                                        if isinstance(catalog_entry, dict):
                                            st.session_state.window_click_params_list[window_idx]['height_mm'] = int(catalog_entry.get('height', 1200))
                                            st.session_state.window_click_params_list[window_idx]['base_mm'] = int(catalog_entry.get('base', 900))
                                        else:
                                            # 古い形式の場合（幅のみ）
                                            st.session_state.window_click_params_list[window_idx]['height_mm'] = 1200
                                            st.session_state.window_click_params_list[window_idx]['base_mm'] = 900
                                    st.rerun()
                            
                            with col2:
                                window_height_mm = st.number_input(
                                    f"窓長さ(高さ) (mm)",
                                    min_value=50,
                                    max_value=3000,
                                    value=st.session_state.window_click_params_list[window_idx].get('height_mm', 1200),
                                    step=1,
                                key=f"window_height_click_{window_idx}_{window_model}"
                                )
                                st.session_state.window_click_params_list[window_idx]['height_mm'] = window_height_mm
                            
                            with col3:
                                window_base_mm = st.number_input(
                                    f"床から窓下端 (mm)",
                                    min_value=0,
                                    max_value=5000,
                                    value=st.session_state.window_click_params_list[window_idx].get('base_mm', 900),
                                    step=1,
                                key=f"window_base_click_{window_idx}_{window_model}"
                                )
                                st.session_state.window_click_params_list[window_idx]['base_mm'] = window_base_mm
                            
                            # パラメータを保存
                            window_params_to_save.append({
                                'model': window_model,
                                'width_mm': WINDOW_CATALOG.get(window_model, {}).get("width", 0) if isinstance(WINDOW_CATALOG.get(window_model), dict) else 0,
                                'height_mm': window_height_mm,
                                'base_mm': window_base_mm
                            })
                        
                        # 実行ボタンを表示
                        if st.button("🪟 窓追加実行", type="primary", key="btn_window_exec_top"):
                            # 選択された壁とパラメータをセッションに保存してから選択リストをクリア
                            st.session_state.window_walls_to_process = list(st.session_state.selected_walls_for_window)
                            st.session_state.window_click_params_list_to_process = window_params_to_save
                            st.session_state.selected_walls_for_window = []
                            st.session_state.skip_click_processing = True  # クリック処理をスキップ
                            # 即座にrerunして選択状態をクリア（次のrerunで実際の処理を実行）
                            st.rerun()
                elif edit_mode == "線を削除":
                    # 線削除モード：壁線クリック選択（複数本可能）
                    num_selected = len(st.session_state.selected_walls_for_delete)
                    if num_selected == 0:
                        pass
                        #st.write("💡 削除したい壁線をクリックしてください（複数選択可能）")
                    else:
                        #st.success(f"✅ **{num_selected}本選択完了**\n\n→ さらに削除する壁線を追加する場合は下の編集画面でクリック\n\n→ 確定する場合は下の「🗑️ 削除実行」ボタンをクリックしてください")
                        
                        # 削除実行ボタン（選択完了メッセージの直後、画像の前に表示）
                        st.markdown("---")
                        if st.button("🗑️ 削除実行", type="primary", key="btn_delete_exec_top"):
                            # 選択された壁をセッションに保存してから選択リストをクリア
                            st.session_state.delete_walls_to_process = list(st.session_state.selected_walls_for_delete)
                            st.session_state.selected_walls_for_delete = []
                            st.session_state.skip_click_processing = True  # クリック処理をスキップ
                            # 即座にrerunして選択状態をクリア（次のrerunで実際の処理を実行）
                            st.rerun()
                elif edit_mode == "階段を配置":
                    # 階段追加モード：2点選択
                    if len(st.session_state.rect_coords_list) > 0:
                        #st.success(f"✅ **{len(st.session_state.rect_coords_list)}箇所の配置範囲を選択完了**\n\n→ さらに追加する場合は下の編集画面で次の2点をクリック\n\n→ 確定する場合は下で階段パターンを選択して「🪜 階段配置実行」ボタンをクリックしてください")
                        
                        # 階段パターン選択
                        st.markdown("---")
                        st.markdown("### 🪜 階段パターンを選択")
                        
                        stair_pattern_key = st.selectbox(
                            "階段の種類",
                            list(STAIR_PATTERNS.keys()),
                            format_func=lambda x: STAIR_PATTERNS[x]["display_name"],
                            help="配置する階段のパターンを選択してください",
                            key="stair_pattern_select"
                        )
                        
                        # 選択されたパターンの説明を表示
                        st.caption(f"📝 {STAIR_PATTERNS[stair_pattern_key]['description']}")
                        
                        # 階段パターンの参照図を折りたたみで表示
                        with st.expander("📐 階段パターンの参照図を表示"):
                            stair_img_path = BASE_DIR / "stair_pattern_images" / "stair_patterns_reference.png"
                            try:
                                if stair_img_path.exists():
                                    img = Image.open(stair_img_path)
                                    st.image(img, caption="階段パターン一覧（番号は各パターンの識別番号）", width=300)
                                else:
                                    st.info(f"📋 参照画像が見つかりません: {stair_img_path.name}")
                            except Exception as e:
                                st.warning(f"⚠️ 参照画像が読み込めません: {stair_img_path.name} (エラー: {str(e)})")
                        
                        # 階段配置実行ボタン
                        if st.button("🪜 階段配置実行", type="primary", key="stair_exec"):
                            st.session_state.execute_stair_placement = True
                            st.session_state.selected_stair_pattern = stair_pattern_key
                            st.rerun()
                    else:
                        pass
                        #st.write("💡 画像をクリックして四角形の対角線上の2点を指定してください")
                
                # 線を結合・窓を追加・線を削除モードは壁線クリック選択なので、ここでのメッセージ表示は不要
                elif edit_mode not in ("線を結合", "窓を追加", "線を削除"):
                    # その他のモード：2点選択
                    
                    # 線を追加モード：rect_coords_listに選択がある場合は実行ボタンを表示
                    if edit_mode == "線を追加" and len(st.session_state.rect_coords_list) > 0:
                        num_rects = len(st.session_state.rect_coords_list)
                        #st.success(f"✅ **{num_rects}本の線を選択完了**\n\n→ さらに線を追加する場合は下の編集画面で次の2点をクリック\n\n→ 確定する場合は下の「➕ 線追加実行」ボタンをクリックしてください")
                        
                        # 線追加実行ボタン（選択完了メッセージの直後、画像の前に表示）
                        st.markdown("---")
                        if st.button("➕ 線追加実行", type="primary", key="btn_add_line_exec_top"):
                            # 実行フラグを立てて処理実行
                            st.session_state.add_line_execute = True
                            st.rerun()
                    
                    if len(st.session_state.rect_coords) == 1:
                        pass
                        #st.info(f"✓ 1点目選択: ({st.session_state.rect_coords[0][0]}, {st.session_state.rect_coords[0][1]})")
                    elif len(st.session_state.rect_coords) == 2:
                        # 窓追加モードで自動追加される場合は、前のrerunでrect_coordsがクリアされるため、
                        # このブロックに到達しない。失敗時のみここに到達する
                        if edit_mode == "線を追加":
                            # 線を追加モード：2点選択完了時の処理
                            # すでに上で表示しているのでここでは何もしない
                            pass
                        elif edit_mode != "窓を追加":
                            p1, p2 = st.session_state.rect_coords
                            x1, y1 = min(p1[0], p2[0]), min(p1[1], p2[1])
                            x2, y2 = max(p1[0], p2[0]), max(p1[1], p2[1])
                            color_name = ["赤", "緑", "青", "黄", "マゼンタ", "シアン"][len(st.session_state.rect_coords_list) % 6]
                            #st.success(f"✅ 2点選択完了（{color_name}）: ({x1}, {y1}) - ({x2}, {y2})")
                    
                    # オブジェクト配置モード：家具のオプション選択を画像の前に表示
                    if edit_mode == "オブジェクトを配置" and len(st.session_state.rect_coords_list) > 0:
                        st.markdown("---")
                        st.markdown("### 🪑 家具のオプションを選択")
                        
                        col_height, col_color = st.columns(2)
                        
                        with col_height:
                            height_option = st.selectbox(
                                "高さ",
                                list(FURNITURE_HEIGHT_OPTIONS.keys()),
                                help="家具の高さを選択してください",
                                key="furniture_height_option"
                            )
                        
                        with col_color:
                            color_option = st.selectbox(
                                "配色",
                                list(FURNITURE_COLOR_OPTIONS.keys()),
                                help="家具の色を選択してください",
                                key="furniture_color_option"
                            )
                        
                        # 選択された高さを取得（天井合わせの場合は壁の高さ）
                        if height_option == "天井合わせ":
                            json_data = json.loads(st.session_state.json_bytes.decode("utf-8"))
                            walls = json_data['walls']
                            heights = [w.get('height', 2.4) for w in walls if 'height' in w]
                            selected_height = max(heights) if heights else 2.4
                            height_display = f"天井合わせ（{selected_height*100:.0f}cm）"
                        else:
                            selected_height = FURNITURE_HEIGHT_OPTIONS[height_option]
                            height_display = height_option
                        
                        # セッションステートに保存
                        st.session_state.furniture_params = {
                            'height_option': height_option,
                            'color_option': color_option,
                            'selected_height': selected_height
                        }
                        
                        # 選択された家具の情報を表示
                        #st.info(f"**{color_option}の家具**\n\n高さ: {height_display}")
                        
                        # 配置範囲のサイズを予測表示
                        if len(st.session_state.rect_coords_list) > 0:
                            rect = st.session_state.rect_coords_list[0]
                            p1, p2 = rect
                            json_data = json.loads(st.session_state.json_bytes.decode("utf-8"))
                            x_start, y_start, width, depth = _snap_to_grid(
                                (p1[0], p1[1], p2[0], p2[1]), 
                                json_data, 
                                st.session_state.viz_scale
                            )
                            #st.success(f"📐 配置サイズ: 幅{width*100:.0f}cm × 奥行き{depth*100:.0f}cm × 高さ{selected_height*100:.0f}cm")
                        
                        if st.button("🪑 オブジェクト配置実行", type="primary", key="furniture_exec"):
                            st.session_state.execute_furniture_placement = True
                            st.rerun()
                    
                    # モード別の説明メッセージ
                    #if edit_mode == "線を追加":
                        #st.write("💡 追加したい壁の端点2点を指定してください")
                    #else:
                        #st.write("💡 画像をクリックして四角形の対角線上の2点を指定してください")
                    
                    # 窓追加モードで2点選択完了時：壁検出結果をハイライト表示（線を結合モードは除外）
                    if edit_mode == "窓を追加" and len(st.session_state.rect_coords) == 2:
                        try:
                            json_data_check = json.loads(st.session_state.json_bytes.decode("utf-8"))
                            walls_check = json_data_check['walls']
                            
                            all_x_check = [w['start'][0] for w in walls_check] + [w['end'][0] for w in walls_check]
                            all_y_check = [w['start'][1] for w in walls_check] + [w['end'][1] for w in walls_check]
                            min_x_check, max_x_check = min(all_x_check), max(all_x_check)
                            min_y_check, max_y_check = min(all_y_check), max(all_y_check)
                            
                            scale_check = int(viz_scale)
                            margin_check = 50
                            img_height_check = viz_img.height
                            
                            p1_check, p2_check = st.session_state.rect_coords
                            x1_check, y1_check = min(p1_check[0], p2_check[0]), min(p1_check[1], p2_check[1])
                            x2_check, y2_check = max(p1_check[0], p2_check[0]), max(p1_check[1], p2_check[1])
                            
                            rect_check = {
                                'left': x1_check,
                                'top': y1_check,
                                'width': x2_check - x1_check,
                                'height': y2_check - y1_check
                            }
                            
                            # 端点のみを囲む操作に対応するため、厳密フィルタではなく端点/交差ベースのフィルタを使用
                            walls_in_rect_check = _filter_walls_by_endpoints_in_rect(
                                walls_check, rect_check, scale_check, margin_check,
                                img_height_check, min_x_check, min_y_check, max_x_check, max_y_check,
                                tolerance=0, debug=False
                            )

                            # 端点が重なって複数の壁が検出される場合、縦横を判定して最適な2本を選択
                            try:
                                # デバッグ: 検出された全ての壁の情報を表示
                                try:
                                    all_wall_details = []
                                    for w in walls_in_rect_check:
                                        dx = abs(w['end'][0] - w['start'][0])
                                        dy = abs(w['end'][1] - w['start'][1])
                                        direction = "縦" if dx < dy else "横"
                                        all_wall_details.append(f"ID{w['id']}({direction})")
                                    append_debug(f"Detected walls before filtering: {', '.join(all_wall_details)}")
                                except:
                                    pass
                                
                                if len(walls_in_rect_check) >= 3:
                                    # 3本以上：縦横を分類して最も近い平行な壁のペアを選ぶ
                                    best_pair = _select_best_wall_pair_from_4(walls_in_rect_check)
                                    walls_in_rect_filtered = best_pair if best_pair else walls_in_rect_check[:2]
                                else:
                                    # 2本以下の場合はそのまま使用
                                    walls_in_rect_filtered = walls_in_rect_check
                            except Exception:
                                walls_in_rect_filtered = walls_in_rect_check



                            if len(walls_in_rect_filtered) in (2, 3):
                                # プレビューで2本検出された場合、確定集合にも反映して表示を整合させる
                                try:
                                    walls_in_rect_confirmed = walls_in_rect_filtered
                                    # プレビューで2本検出された四角形情報とIDをセッションに保存
                                    try:
                                        st.session_state['last_preview_pair'] = [walls_in_rect_filtered[0]['id'], walls_in_rect_filtered[1]['id']]
                                        st.session_state['last_preview_rect'] = rect_preview
                                        # 検出/フィルタ済みIDもセッション保存して実行時に優先できるようにする
                                        try:
                                            st.session_state['last_preview_detected_ids'] = [w.get('id') for w in walls_in_rect_check]
                                            st.session_state['last_preview_filtered_ids'] = [w.get('id') for w in walls_in_rect_filtered]
                                        except Exception:
                                            pass
                                    except Exception:
                                        pass
                                except Exception:
                                    pass
                                # プレビュー確定表示は不要になったためUI非表示（内部データは保持）
                                try:
                                    preview_debug_confirm = []
                                    for w in walls_check:
                                        x1w = int((w['start'][0] - min_x_check) * scale_check) + margin_check
                                        y1w = img_height_check - (int((w['start'][1] - min_y_check) * scale_check) + margin_check)
                                        x2w = int((w['end'][0] - min_x_check) * scale_check) + margin_check
                                        y2w = img_height_check - (int((w['end'][1] - min_y_check) * scale_check) + margin_check)
                                        in_rect = (
                                            (rect_check['left'] <= x1w <= rect_check['left'] + rect_check['width'] and rect_check['top'] <= y1w <= rect_check['top'] + rect_check['height']) or
                                            (rect_check['left'] <= x2w <= rect_check['left'] + rect_check['width'] and rect_check['top'] <= y2w <= rect_check['top'] + rect_check['height']) or
                                            _line_intersects_rect(x1w, y1w, x2w, y2w, rect_check, tolerance=20)
                                        )
                                        preview_debug_confirm.append({'id': w.get('id'), 'start_px': (x1w, y1w), 'end_px': (x2w, y2w), 'in_rect': in_rect})
                                    try:
                                        append_debug(f"Preview confirmed mapping: detected={[d['id'] for d in preview_debug_confirm if d.get('in_rect')]}, total_checked={len(preview_debug_confirm)}")
                                    except Exception:
                                        pass
                                except Exception:
                                    pass
                                # デバッグ: 選択された壁の詳細情報を表示
                                try:
                                    wall_details = []
                                    for w in walls_in_rect_filtered:
                                        dx = abs(w['end'][0] - w['start'][0])
                                        dy = abs(w['end'][1] - w['start'][1])
                                        direction = "縦" if dx < dy else "横"
                                        wall_details.append(f"ID{w['id']}({direction}, dx={dx:.2f}, dy={dy:.2f})")
                                    st.info(f"🎯 この範囲に2本の壁が検出されました\n検出数: {len(walls_in_rect_check)}本 → フィルタ後: {len(walls_in_rect_filtered)}本\n選択された壁: {', '.join(wall_details)}")
                                except Exception:
                                    st.info(f"🎯 この範囲に2本の壁が検出されました（ID: {walls_in_rect_filtered[0]['id']}, {walls_in_rect_filtered[1]['id']}）\n検出数: {len(walls_in_rect_check)}本 → フィルタ後: {len(walls_in_rect_filtered)}本")
                            elif len(walls_in_rect_filtered) == 0:
                                st.error("❌ **この範囲に壁が検出されませんでした。**\n\n💡 **窓で分断された2本の壁を両方含むように**、もう少し広い範囲を選択してください。")
                            elif len(walls_in_rect_filtered) == 1:
                                st.warning(f"⚠️ **この範囲に1本の壁しか検出されません。**\n\n💡 **窓で分断された2本の壁を両方含むように**選択してください。\n\n窓の両側（上下または左右）にある壁が2本とも範囲内に入るように、選択範囲を広げてください。")
                            else:
                                st.warning(f"⚠️ **この範囲に{len(walls_in_rect_filtered)}本の壁が検出されました。**\n\n💡 選択範囲を狭めて余分な壁が含まれないように調整してください。")
                        except Exception:
                            pass
                
                # クリック可能な画像を表示（キーを動的に変更して値をリセット）
                # edit_modeを含めることで、モード切り替え時に座標がリセットされる
                # selection_reset_counterを含めることで、リセット後に座標がクリアされる
                reset_counter = st.session_state.get('selection_reset_counter', 0)
                coord_key = f"image_coords_{edit_mode}_{len(st.session_state.rect_coords_list)}_{len(st.session_state.rect_coords)}_{reset_counter}"
                
                st.markdown(
                    """
                    <p style="font-size: 12px; color: #666; margin-bottom: 8px;">
                    <b>注:</b> 編集画面が表示されないときは選択リセットか表示サイズ調整を押してください。
                    </p>
                    """,
                    unsafe_allow_html=True
                )
                
                # ズームコントロール（ステップ3）
                if 'editor_zoom_level' not in st.session_state:
                    st.session_state.editor_zoom_level = 1.0
                
                col_zoom_label, col_zoom1, col_zoom2, col_zoom_space = st.columns([3, 1, 1, 7])
                with col_zoom_label:
                    st.markdown(f"表示サイズ調整: {st.session_state.editor_zoom_level*100:.0f}%")
                with col_zoom1:
                    if st.button("🔍−", key="step3_zoom_out"):
                        st.session_state.editor_zoom_level = max(0.2, st.session_state.editor_zoom_level - 0.2)
                        st.rerun()
                with col_zoom2:
                    if st.button("🔍+", key="step3_zoom_in"):
                        st.session_state.editor_zoom_level = min(1.6, st.session_state.editor_zoom_level + 0.2)
                        st.rerun()
                
                
                # 画像データの検証（表示エラー対策）
                if display_img_resized is None:
                    st.warning("⚠️ 画像データを再生成しています...")
                    st.rerun()
                
                if display_img_resized.size[0] == 0 or display_img_resized.size[1] == 0:
                    st.warning("⚠️ 画像サイズが不正です。再試行しています...")
                    # ズームレベルをリセット
                    st.session_state.editor_zoom_level = 1.0
                    st.rerun()
                
                # 画像を元のサイズで表示（リサイズなし）
                value = streamlit_image_coordinates(
                    display_img_resized,
                    key=coord_key
                )
                
                # リセットボタンを画像の下に配置
                col_reset, col_space = st.columns([2, 10])
                with col_reset:
                    if st.button("🗑️ 選択リセット"):
                        _reset_selection_state()
                        st.rerun()
                
                # リサイズ時とズーム時の座標変換
                if value is not None and value.get("x") is not None:
                    # ズーム補正を適用
                    zoom_level = st.session_state.get('editor_zoom_level', 1.0)
                    adjusted_x = value["x"] / zoom_level
                    adjusted_y = value["y"] / zoom_level
                    
                    # 元の座標に変換
                    if scale_ratio != 1.0:
                        ox, oy = _display_to_original(adjusted_x, adjusted_y, scale_ratio)
                        value["x"] = ox
                        value["y"] = oy
                    else:
                        value["x"] = adjusted_x
                        value["y"] = adjusted_y

                # デバッグ: クリック座標を表示
                #if value is not None and value.get("x") is not None:
                #    st.caption(
                #        f"クリック座標: raw=({value['x']}, {value['y']}) | "
                #        f"表示画像サイズ={display_img_resized.width}x{display_img_resized.height}px | "
                #        f"scale_ratio={scale_ratio:.3f}"
                #    )
                
                # クリックされた座標を記録（重複チェック）
                if value is not None and value.get("x") is not None:
                    new_point = (value["x"], value["y"])
                    
                    if edit_mode == "線を結合":
                        # 線を結合モード：壁線をクリックで選択（最大2本）
                        # 同じ座標の連続処理を防ぐ（無限ループ防止）
                        if st.session_state.last_click == new_point:
                            # 既に処理済みのクリックなのでスキップ
                            pass
                        else:
                            try:
                                json_data_merge = json.loads(st.session_state.json_bytes.decode("utf-8"))
                                walls_merge = json_data_merge.get('walls', [])
                                
                                all_x_merge = [w['start'][0] for w in walls_merge] + [w['end'][0] for w in walls_merge]
                                all_y_merge = [w['start'][1] for w in walls_merge] + [w['end'][1] for w in walls_merge]
                                min_x_merge = min(all_x_merge)
                                min_y_merge = min(all_y_merge)
                                max_x_merge = max(all_x_merge)
                                max_y_merge = max(all_y_merge)
                                
                                scale_merge = int(st.session_state.viz_scale)
                                margin_merge = 50
                                img_height_merge = viz_img.height
                                
                                # クリック位置から最も近い壁を検出
                                nearest_wall, distance = _find_nearest_wall_from_click(
                                    new_point[0], new_point[1],
                                    walls_merge, scale_merge, margin_merge,
                                    img_height_merge, min_x_merge, min_y_merge, max_x_merge, max_y_merge,
                                    threshold=20
                                )
                                
                                if nearest_wall is not None:
                                    # 奇数本選択中で、最後の壁と同じ場合のみ削除（やり直し用）
                                    # それ以外は常に追加（同じ壁を複数の結合ペアで使用可能）
                                    current_count = len(st.session_state.selected_walls_for_merge)
                                    if (current_count % 2 == 1 and 
                                        current_count > 0 and 
                                        st.session_state.selected_walls_for_merge[-1] == nearest_wall):
                                        # 奇数本目選択中で、最後に選択した壁と同じ場合のみ削除
                                        st.session_state.selected_walls_for_merge.remove(nearest_wall)
                                    else:
                                        # それ以外は常に追加（同じ壁を別の結合ペアで再利用可能）
                                        st.session_state.selected_walls_for_merge.append(nearest_wall)
                                    st.session_state.last_click = new_point
                                    st.rerun()
                            except Exception as e:
                                st.error(f"壁選択エラー: {e}")
                    elif edit_mode == "窓を追加":
                        # 窓追加モード：壁線をクリックで選択（最大2本）
                        if st.session_state.last_click == new_point:
                            pass
                        else:
                            try:
                                json_data_window = json.loads(st.session_state.json_bytes.decode("utf-8"))
                                walls_window = json_data_window.get('walls', [])
                                
                                all_x_window = [w['start'][0] for w in walls_window] + [w['end'][0] for w in walls_window]
                                all_y_window = [w['start'][1] for w in walls_window] + [w['end'][1] for w in walls_window]
                                min_x_window = min(all_x_window)
                                min_y_window = min(all_y_window)
                                max_x_window = max(all_x_window)
                                max_y_window = max(all_y_window)
                                
                                scale_window = int(st.session_state.viz_scale)
                                margin_window = 50
                                img_height_window = viz_img.height
                                
                                # クリック位置から最も近い壁を検出
                                nearest_wall, distance = _find_nearest_wall_from_click(
                                    new_point[0], new_point[1],
                                    walls_window, scale_window, margin_window,
                                    img_height_window, min_x_window, min_y_window, max_x_window, max_y_window,
                                    threshold=20
                                )
                                
                                if nearest_wall is not None:
                                    # 奇数本選択中で、最後の壁と同じ場合のみ削除（やり直し用）
                                    # それ以外は常に追加（同じ壁を複数の窓ペアで使用可能）
                                    current_count = len(st.session_state.selected_walls_for_window)
                                    if (current_count % 2 == 1 and 
                                        current_count > 0 and 
                                        st.session_state.selected_walls_for_window[-1] == nearest_wall):
                                        # 奇数本目選択中で、最後に選択した壁と同じ場合のみ削除
                                        st.session_state.selected_walls_for_window.remove(nearest_wall)
                                    else:
                                        # それ以外は常に追加（同じ壁を別の窓ペアで再利用可能）
                                        st.session_state.selected_walls_for_window.append(nearest_wall)
                                    st.session_state.last_click = new_point
                                    st.rerun()
                            except Exception as e:
                                st.error(f"壁選択エラー: {e}")
                    elif edit_mode == "線を削除":
                        # 線削除モード：壁線をクリックで選択（複数本可能）
                        if st.session_state.last_click == new_point:
                            pass
                        else:
                            try:
                                json_data_delete = json.loads(st.session_state.json_bytes.decode("utf-8"))
                                walls_delete = json_data_delete.get('walls', [])
                                
                                all_x_delete = [w['start'][0] for w in walls_delete] + [w['end'][0] for w in walls_delete]
                                all_y_delete = [w['start'][1] for w in walls_delete] + [w['end'][1] for w in walls_delete]
                                min_x_delete = min(all_x_delete)
                                min_y_delete = min(all_y_delete)
                                max_x_delete = max(all_x_delete)
                                max_y_delete = max(all_y_delete)
                                
                                scale_delete = int(st.session_state.viz_scale)
                                margin_delete = 50
                                img_height_delete = viz_img.height
                                
                                # クリック位置から最も近い壁を検出
                                nearest_wall, distance = _find_nearest_wall_from_click(
                                    new_point[0], new_point[1],
                                    walls_delete, scale_delete, margin_delete,
                                    img_height_delete, min_x_delete, min_y_delete, max_x_delete, max_y_delete,
                                    threshold=20
                                )
                                
                                if nearest_wall is not None:
                                    # 既に選択されている場合は選択解除
                                    if nearest_wall in st.session_state.selected_walls_for_delete:
                                        st.session_state.selected_walls_for_delete.remove(nearest_wall)
                                    else:
                                        # 複数本選択可能
                                        st.session_state.selected_walls_for_delete.append(nearest_wall)
                                    st.session_state.last_click = new_point
                                    st.rerun()
                            except Exception as e:
                                st.error(f"壁選択エラー: {e}")
                    elif edit_mode == "スケール校正":
                        # スケール校正モード：壁を1クリックで選択
                        if st.session_state.last_click != new_point:
                            try:
                                # 壁データと座標範囲を取得
                                json_data_calib = json.loads(st.session_state.json_bytes.decode("utf-8"))
                                walls_calib = json_data_calib.get("walls", [])
                                
                                all_x_calib = []
                                all_y_calib = []
                                for w in walls_calib:
                                    if "start" in w and "end" in w:
                                        all_x_calib.extend([w["start"][0], w["end"][0]])
                                        all_y_calib.extend([w["start"][1], w["end"][1]])
                                
                                if all_x_calib and all_y_calib:
                                    min_x_calib = min(all_x_calib)
                                    max_x_calib = max(all_x_calib)
                                    min_y_calib = min(all_y_calib)
                                    max_y_calib = max(all_y_calib)
                                    
                                    scale_calib = int(st.session_state.viz_scale)
                                    margin_calib = 50
                                    img_height_calib = Image.open(io.BytesIO(st.session_state.viz_bytes)).height
                                    
                                    # クリック位置から最も近い壁を検出
                                    nearest_wall, distance = _find_nearest_wall_from_click(
                                        click_point[0], click_point[1],
                                        walls_calib, scale_calib, margin_calib,
                                        img_height_calib, min_x_calib, min_y_calib, max_x_calib, max_y_calib,
                                        threshold=20
                                    )
                                    
                                    if nearest_wall:
                                        # 壁を選択
                                        st.session_state.selected_wall_for_calibration = nearest_wall
                                    else:
                                        # 閾値外の場合は選択解除
                                        st.session_state.selected_wall_for_calibration = None
                                    
                                    st.session_state.last_click = new_point
                                    st.rerun()
                            except Exception as e:
                                st.error(f"壁選択エラー: {e}")
                    else:
                        # その他のモード：2点選択
                        if len(st.session_state.rect_coords) < 2:
                            if len(st.session_state.rect_coords) == 0 or st.session_state.last_click != new_point:
                                st.session_state.rect_coords.append(new_point)
                                st.session_state.last_click = new_point
                                
                                # 窓追加モード、線を追加モード、またはオブジェクト配置モードで2点目クリック時：
                                # 2本の壁が検出されたら自動追加（オブジェクト配置では四角形をそのまま追加）
                                # 注：線を結合モードは壁線クリック選択のため除外
                                if (edit_mode in ("窓を追加", "線を追加", "オブジェクトを配置", "階段を配置")) and len(st.session_state.rect_coords) == 2:
                                    try:
                                        json_data_auto = json.loads(st.session_state.json_bytes.decode("utf-8"))
                                        walls_auto = json_data_auto['walls']
                                        
                                        all_x_auto = [w['start'][0] for w in walls_auto] + [w['end'][0] for w in walls_auto]
                                        all_y_auto = [w['start'][1] for w in walls_auto] + [w['end'][1] for w in walls_auto]
                                        min_x_auto, max_x_auto = min(all_x_auto), max(all_x_auto)
                                        min_y_auto, max_y_auto = min(all_y_auto), max(all_y_auto)
                                        
                                        scale_auto = int(st.session_state.viz_scale)
                                        margin_auto = 50
                                        img_height_auto = Image.open(io.BytesIO(st.session_state.viz_bytes)).height
                                        
                                        p1_auto, p2_auto = st.session_state.rect_coords
                                        x1_auto, y1_auto = min(p1_auto[0], p2_auto[0]), min(p1_auto[1], p2_auto[1])
                                        x2_auto, y2_auto = max(p1_auto[0], p2_auto[0]), max(p1_auto[1], p2_auto[1])
                                        
                                        rect_auto = {
                                            'left': x1_auto,
                                            'top': y1_auto,
                                            'width': x2_auto - x1_auto,
                                            'height': y2_auto - y1_auto
                                        }
                                        
                                        # 窓追加モードと線を結合モードは端点/交差ベースで検出（端点だけ囲む操作に対応）
                                        if edit_mode in ("窓を追加", "線を結合"):
                                            walls_in_rect_auto = _filter_walls_by_endpoints_in_rect(
                                                walls_auto, rect_auto, scale_auto, margin_auto,
                                                img_height_auto, min_x_auto, min_y_auto, max_x_auto, max_y_auto,
                                                tolerance=0, debug=False
                                            )
                                        else:
                                            # 通常の線結合などは従来通り厳密判定
                                            walls_in_rect_auto = _filter_walls_strictly_in_rect(
                                                walls_auto, rect_auto, scale_auto, margin_auto,
                                                img_height_auto, min_x_auto, min_y_auto, max_x_auto, max_y_auto
                                            )

                                        # 2本の壁が検出された場合のみ自動追加（窓追加のみ、線を結合は除外）
                                        if edit_mode == "窓を追加":
                                            if len(walls_in_rect_auto) == 2:
                                                st.session_state.rect_coords_list.append((p1_auto, p2_auto))
                                                st.session_state.rect_coords = []
                                                st.session_state.last_click = None
                                                try:
                                                    append_debug(f"Auto-added selection (2 walls detected): ids={[w.get('id') for w in walls_in_rect_auto]}")
                                                except Exception:
                                                    pass
                                                st.rerun()
                                            else:
                                                # 端点が多く2本に絞れない場合、角度フィルタで2本に絞れれば自動追加する
                                                try:
                                                    if len(walls_in_rect_auto) >= 2:
                                                        angle_threshold_preview = 30.0
                                                        angles = [math.radians(_wall_angle_deg(w)) for w in walls_in_rect_auto]
                                                        sx = sum(math.cos(a) for a in angles) if angles else 0
                                                        sy = sum(math.sin(a) for a in angles) if angles else 0
                                                        if sx == 0 and sy == 0:
                                                            avg_angle = 0.0
                                                        else:
                                                            avg_angle = math.degrees(math.atan2(sy, sx))

                                                        kept_preview = [w for w in walls_in_rect_auto if _angle_diff_deg(_wall_angle_deg(w), avg_angle) < angle_threshold_preview]
                                                        if len(kept_preview) == 2:
                                                            # 条件を満たすので自動で選択を追加
                                                            st.session_state.rect_coords_list.append((p1_auto, p2_auto))
                                                            st.session_state.rect_coords = []
                                                            st.session_state.last_click = None
                                                            try:
                                                                append_debug(f"Auto-added selection (angle-filtered): kept_ids={[w.get('id') for w in kept_preview]}, avg_angle={avg_angle}")
                                                            except Exception:
                                                                pass
                                                            st.rerun()
                                                except Exception:
                                                    pass
                                        else:
                                            # オブジェクト配置モードと線を追加モードでは四角形をそのまま追加（壁検出は不要）
                                            st.session_state.rect_coords_list.append((p1_auto, p2_auto))
                                            st.session_state.rect_coords = []
                                            st.session_state.last_click = None
                                            try:
                                                if edit_mode == "線を追加":
                                                    append_debug(f"Auto-added line-placement selection: rect=({p1_auto},{p2_auto})")
                                                else:
                                                    append_debug(f"Auto-added object-placement selection: rect=({p1_auto},{p2_auto})")
                                            except Exception:
                                                pass
                                            st.rerun()
                                    except Exception:
                                        pass
                                
                                st.rerun()  # 画像を再描画して選択点を表示
                
                # 選択完了時のUI
                if edit_mode == "線を削除" and len(st.session_state.rect_coords) == 2:
                    # 削除モード：2点選択完了（四角形）
                    p1, p2 = st.session_state.rect_coords
                    x1, y1 = min(p1[0], p2[0]), min(p1[1], p2[1])
                    x2, y2 = max(p1[0], p2[0]), max(p1[1], p2[1])
                    st.success(f"✅ 2点選択完了: ({x1}, {y1}) - ({x2}, {y2})")
                
                    with col_add:
                        if st.button("➕ この選択を追加", type="primary"):
                            # 現在の2点をリストに追加
                            st.session_state.rect_coords_list.append((p1, p2))
                            # 現在の選択をクリア
                            st.session_state.rect_coords = []
                            st.session_state.last_click = None
                            st.rerun()
                elif edit_mode != "線を削除" and edit_mode != "線を結合" and len(st.session_state.rect_coords) == 2:
                    # 追加モード（線を結合以外）：2点選択完了
                    p1, p2 = st.session_state.rect_coords
                    x1, y1 = min(p1[0], p2[0]), min(p1[1], p2[1])
                    x2, y2 = max(p1[0], p2[0]), max(p1[1], p2[1])
                    st.success(f"✅ 2点選択完了: ({x1}, {y1}) - ({x2}, {y2})")
                
                    with col_add:
                        if st.button("➕ この選択を追加", type="primary"):
                            # 現在の2点をリストに追加
                            st.session_state.rect_coords_list.append((p1, p2))
                            # 現在の選択をクリア
                            st.session_state.rect_coords = []
                            st.session_state.last_click = None
                            st.rerun()
                
                # 確定済み選択の表示
                # NOTE: ユーザー要望により、線を結合／線を削除／線を追加モードでは追加済みの選択範囲表示を抑制する
                if len(st.session_state.rect_coords_list) > 0 and edit_mode not in ("線を結合", "線を削除", "線を追加", "オブジェクトを配置", "階段を配置"):
                    if edit_mode == "線を削除":
                        st.markdown("### 📋 追加済みの削除対象")
                        for idx, (p1, p2) in enumerate(st.session_state.rect_coords_list):
                            color_name = ["赤", "緑", "青", "黄", "マゼンタ", "シアン"][idx % 6]
                            st.write(f"#{idx+1}（{color_name}）: ({p1[0]}, {p1[1]})")
                    elif edit_mode == "窓を追加":
                        # 窓追加モードの場合、各選択範囲の壁検出状況を表示
                        try:
                            json_data = json.loads(st.session_state.json_bytes.decode("utf-8"))
                            walls = json_data['walls']
                            all_x = [w['start'][0] for w in walls] + [w['end'][0] for w in walls]
                            all_y = [w['start'][1] for w in walls] + [w['end'][1] for w in walls]
                            min_x, max_x = min(all_x), max(all_x)
                            min_y, max_y = min(all_y), max(all_y)
                            scale = int(viz_scale)
                            margin = 50
                            img_width = int((max_x - min_x) * scale) + 2 * margin
                            img_height = int((max_y - min_y) * scale) + 2 * margin
                            
                            # 全ての選択が成功しているかチェック
                            all_successful = True
                            for p1, p2 in st.session_state.rect_coords_list:
                                x1, y1 = min(p1[0], p2[0]), min(p1[1], p2[1])
                                x2, y2 = max(p1[0], p2[0]), max(p1[1], p2[1])
                                rect = {'left': x1, 'top': y1, 'width': x2 - x1, 'height': y2 - y1}
                                # 窓追加モードおよび線を結合モードでは端点/交差ベースで検出（端点だけ囲む操作に対応）
                                if edit_mode in ("窓を追加", "線を結合"):
                                    walls_in_rect = _filter_walls_by_endpoints_in_rect(
                                        walls, rect, scale, margin, img_height, min_x, min_y, max_x, max_y,
                                        tolerance=0, debug=False
                                    )
                                else:
                                    walls_in_rect = _filter_walls_strictly_in_rect(
                                        walls, rect, scale, margin, img_height, min_x, min_y, max_x, max_y
                                    )
                                if len(walls_in_rect) != 2:
                                    all_successful = False
                                    break
                            
                            # 失敗がある場合のみ見出しを表示
                            #if not all_successful:
                            #    st.markdown("### 📋 追加済みの選択範囲（窓）")
                            
                            #for idx, (p1, p2) in enumerate(st.session_state.rect_coords_list):
                            #    x1, y1 = min(p1[0], p2[0]), min(p1[1], p2[1])
                            #    x2, y2 = max(p1[0], p2[0]), max(p1[1], p2[1])
                            #    color_name = ["赤", "緑", "青", "黄", "マゼンタ", "シアン"][idx % 6]
                                
                            #    rect = {'left': x1, 'top': y1, 'width': x2 - x1, 'height': y2 - y1}
                                # 窓追加モードおよび線を結合モードでは端点/交差ベースで検出（以前は厳密フィルタが使われていたため表示が不整合になっていた）
                            #    if edit_mode in ("窓を追加", "線を結合"):
                            #        walls_in_rect = _filter_walls_by_endpoints_in_rect(
                            #            walls, rect, scale, margin, img_height, min_x, min_y, max_x, max_y,
                            #            tolerance=0, debug=False
                            #        )
                            #    else:
                            #        walls_in_rect = _filter_walls_strictly_in_rect(
                            #            walls, rect, scale, margin, img_height, min_x, min_y, max_x, max_y
                            #        )
                                
                                # ハイライト表示（失敗の場合のみ）
                            #    if len(walls_in_rect) != 2:
                            #        if len(walls_in_rect) == 0:
                            #            st.error(f"#{idx+1}（{color_name}）: ({x1}, {y1}) - ({x2}, {y2})\n\n❌ 壁なし → 範囲を広げてください")
                            #        elif len(walls_in_rect) == 1:
                            #            st.warning(f"#{idx+1}（{color_name}）: ({x1}, {y1}) - ({x2}, {y2})\n\n⚠️ 1本のみ → 窓の両側の壁が入るように範囲を広げてください")
                            #        else:
                            #            st.warning(f"#{idx+1}（{color_name}）: ({x1}, {y1}) - ({x2}, {y2})\n\n⚠️ {len(walls_in_rect)}本（多すぎ） → 範囲を狭めてください")
                        except Exception as e:
                            st.error(f"壁検出エラー: {e}")
                        
                        # 窓追加モード: 各窓のパラメータ入力フォームを表示
                        if len(st.session_state.rect_coords_list) > 0:
                            st.markdown("---")
                            st.markdown("### 🪟 窓のサイズを入力")
                            st.info("💡 窓追加のパラメータを画面上部で入力してください（型番選択→窓高さ等）。")
                            
                            # 窓パラメータのデフォルト値を初期化
                            if 'window_params_list' not in st.session_state:
                                st.session_state.window_params_list = []
                            
                            # リストのサイズを調整
                            while len(st.session_state.window_params_list) < len(st.session_state.rect_coords_list):
                                st.session_state.window_params_list.append({
                                    'model': 'J4415/JF4415',
                                    'height_mm': 467,
                                    'base_mm': 1677
                                })
                            
                            # 各窓の入力フォーム
                            for idx in range(len(st.session_state.rect_coords_list)):
                                with st.expander(f"🪟 窓 #{idx+1} のパラメータ", expanded=True):
                                    col1, col2, col3 = st.columns([2, 1, 1])
                                    
                                    # 型番選択
                                    with col1:
                                        catalog_keys = sorted(list(WINDOW_CATALOG.keys()))
                                        catalog_keys.append("カスタム（手入力）")
                                        current_model = st.session_state.window_params_list[idx].get('model', 'J4415/JF4415')
                                        if current_model not in catalog_keys and current_model is not None:
                                            current_model = 'カスタム（手入力）'
                                        
                                        selected_model = st.selectbox(
                                            "型番（窓カタログ）",
                                            catalog_keys,
                                            index=catalog_keys.index(current_model) if current_model in catalog_keys else 0,
                                            key=f"window_model_{idx}"
                                        )
                                        
                                        # 型番が変更された場合、カタログ値で更新してrerun
                                        if selected_model != current_model:
                                            st.session_state.window_params_list[idx]['model'] = selected_model
                                            if selected_model != "カスタム（手入力）" and selected_model in WINDOW_CATALOG:
                                                catalog_entry = WINDOW_CATALOG[selected_model]
                                                if isinstance(catalog_entry, dict):
                                                    st.session_state.window_params_list[idx]['height_mm'] = int(catalog_entry.get('height', 1200))
                                                    st.session_state.window_params_list[idx]['base_mm'] = int(catalog_entry.get('base', 900))
                                                else:
                                                    st.session_state.window_params_list[idx]['height_mm'] = int(catalog_entry)
                                                    st.session_state.window_params_list[idx]['base_mm'] = 900
                                            st.rerun()
                                        
                                        st.session_state.window_params_list[idx]['model'] = selected_model
                                    
                                    # 窓高さ
                                    with col2:
                                        # セッション状態から現在の値を取得
                                        current_h_mm = st.session_state.window_params_list[idx].get('height_mm', 1200)
                                        
                                        # 編集可能なnumber_input（型番も含めたkeyで一意性を確保）
                                        height_mm = st.number_input(
                                            "窓長さ(高さ) (mm)",
                                            min_value=50,
                                            max_value=3000,
                                            value=current_h_mm,
                                            step=1,
                                            key=f"window_height_{idx}_{selected_model}"
                                        )
                                        st.session_state.window_params_list[idx]['height_mm'] = height_mm
                                    
                                    # 床から窓下端
                                    with col3:
                                        # セッション状態から現在の値を取得
                                        current_base_mm = st.session_state.window_params_list[idx].get('base_mm', 900)
                                        
                                        # 編集可能なnumber_input（型番も含めたkeyで一意性を確保）
                                        base_mm = st.number_input(
                                            "床から窓下端 (mm)",
                                            min_value=0,
                                            max_value=5000,
                                            value=current_base_mm,
                                            step=1,
                                            key=f"window_base_{idx}_{selected_model}"
                                        )
                                        st.session_state.window_params_list[idx]['base_mm'] = base_mm
                                    
                                    # デバッグ情報を表示
                                    st.caption(f"💡 現在の設定: 高さ={st.session_state.window_params_list[idx]['height_mm']}mm, "
                                              f"床から={st.session_state.window_params_list[idx]['base_mm']}mm, "
                                              f"合計={st.session_state.window_params_list[idx]['height_mm'] + st.session_state.window_params_list[idx]['base_mm']}mm "
                                              f"({(st.session_state.window_params_list[idx]['height_mm'] + st.session_state.window_params_list[idx]['base_mm'])/1000:.3f}m)")
                            
                            if st.button("🪟 窓追加実行", type="primary", key="window_batch_exec"):
                                st.session_state.execute_window_batch = True
                                st.rerun()
                    else:
                        st.markdown("### 📋 追加済みの選択範囲")
                        for idx, (p1, p2) in enumerate(st.session_state.rect_coords_list):
                            x1, y1 = min(p1[0], p2[0]), min(p1[1], p2[1])
                            x2, y2 = max(p1[0], p2[0]), max(p1[1], p2[1])
                            color_name = ["赤", "緑", "青", "黄", "マゼンタ", "シアン"][idx % 6]
                            st.write(f"#{idx+1}（{color_name}）: ({x1}, {y1}) - ({x2}, {y2})")
                
                # 永続デバッグログ表示（rerun しても残る）
                # 永続デバッグログのUI表示は不要になったため削除（ログはセッションに保持）
                
                # 線を結合モードでクリック選択実行の処理（選択リセットの横のボタンは削除済み）
                # 実行トリガーはメッセージ下のボタンのみ
                
                if edit_mode == "窓を追加":
                    # 窓追加モード：右側に重複して表示していた入力は削除
                    # 四角形が選択されている場合でも、画面上部のフォームで入力してください
                    if len(st.session_state.rect_coords_list) > 0:
                        # セッションから現在の窓高さを決定（mm->m 変換を優先）
                        if st.session_state.get('window_execution_params'):
                            cur_wh_m = st.session_state['window_execution_params'].get('window_height', 1.2)
                        elif st.session_state.get('window_height_input_mm'):
                            cur_wh_m = float(st.session_state['window_height_input_mm']) / 1000.0
                        elif st.session_state.get('window_height_display_mm'):
                            cur_wh_m = float(st.session_state['window_height_display_mm']) / 1000.0
                        else:
                            cur_wh_m = 1.2
                        
                        # 実行は画面上部のフォームで行うため、ここでは入力値の確認のみ表示
                        params_preview = st.session_state.get('window_execution_params', None)
                        if params_preview is not None:
                            wh = params_preview.get('window_height', cur_wh_m)
                            bh = params_preview.get('base_height', 0.9)
                            bh_mm = params_preview.get('base_height_mm', int(bh * 1000))
                            rh = params_preview.get('room_height', 2.4)
                            ceiling_height = rh - (bh + wh)
                            st.info(f"📐 床側の壁: {bh:.2f}m ({bh_mm}mm)、天井側の壁: {ceiling_height:.2f}m")
                            if ceiling_height < 0:
                                st.error("⚠️ 窓のサイズが部屋の高さを超えています")

                    # 追加: 現在の2点選択がある場合、実行前にデバッグ情報を表示
                    if len(st.session_state.get('rect_coords', [])) == 2:
                        # プレビュー時の詳細デバッグ表示は不要になったため非表示にします
                        try:
                            p1, p2 = tuple(st.session_state['rect_coords'])
                            if st.session_state.get('json_bytes'):
                                json_data_preview = json.loads(st.session_state.json_bytes.decode('utf-8'))
                                walls_preview = json_data_preview.get('walls', [])
                                all_x = [w['start'][0] for w in walls_preview] + [w['end'][0] for w in walls_preview]
                                all_y = [w['start'][1] for w in walls_preview] + [w['end'][1] for w in walls_preview]
                                min_x, max_x = min(all_x), max(all_x)
                                min_y, max_y = min(all_y), max(all_y)
                                scale_preview = int(st.session_state.get('viz_scale', 100))
                                margin_preview = 50
                                img_height_preview = int((max_y - min_y) * scale_preview) + 2 * margin_preview
                                rect_preview = {
                                    'left': min(p1[0], p2[0]),
                                    'top': min(p1[1], p2[1]),
                                    'width': abs(p2[0] - p1[0]),
                                    'height': abs(p2[1] - p1[1])
                                }
                                # 内部検証は行うが表示は行わない（必要ならログに出す）
                                walls_hit, debug_info_preview = _filter_walls_by_endpoints_in_rect(
                                    walls_preview, rect_preview, scale_preview, margin_preview, img_height_preview,
                                    min_x, min_y, max_x, max_y, tolerance=0, debug=True
                                )
                                try:
                                    append_debug(f"Window-add preview: detected_ids={[w.get('id') for w in walls_hit]}, total_checked={len(debug_info_preview)}")
                                except Exception:
                                    pass
                        except Exception:
                            pass
                
                # 窓追加モードで一括実行ボタンが押された場合の処理
                if edit_mode == "窓を追加" and (st.session_state.get('execute_window_now') or st.session_state.get('execute_window_batch')):
                        # フラグをクリア
                        st.session_state.execute_window_now = False
                        st.session_state.execute_window_batch = False
                        
                        try:
                            try:
                                append_debug(f"Window-add execute: target_rects_count={len(st.session_state.rect_coords_list)}, window_params_count={len(st.session_state.get('window_params_list', []))}")
                            except Exception:
                                pass
                            
                            # 処理対象の四角形リストを作成
                            target_rects = list(st.session_state.rect_coords_list)
                            window_params_list = st.session_state.get('window_params_list', [])
                            
                            if len(target_rects) == 0:
                                st.error("⚠️ 窓の範囲を選択してください")
                                st.stop()
                            
                            if len(window_params_list) < len(target_rects):
                                st.error("⚠️ すべての窓のパラメータを入力してください")
                                st.stop()
                        
                            # JSONデータを読み込み
                            json_data = json.loads(st.session_state.json_bytes.decode("utf-8"))
                            walls = json_data['walls']
                        
                            # 可視化画像のパラメータを取得
                            all_x = [w['start'][0] for w in walls] + [w['end'][0] for w in walls]
                            all_y = [w['start'][1] for w in walls] + [w['end'][1] for w in walls]
                            min_x, max_x = min(all_x), max(all_x)
                            min_y, max_y = min(all_y), max(all_y)
                        
                            scale = int(viz_scale)
                            margin = 50
                            img_width = int((max_x - min_x) * scale) + 2 * margin
                            img_height = int((max_y - min_y) * scale) + 2 * margin
                        
                            # 編集前の画像を保存（比較用）
                            original_viz_bytes = st.session_state.viz_bytes
                        
                            # 元データを保護するためディープコピー
                            import copy
                            original_json_data = copy.deepcopy(json_data)
                            updated_json = json_data
                            
                            # 追加した壁のID（赤色表示用）
                            added_wall_ids = []
                            
                            # 天井高さ（部屋の高さ）を取得
                            heights = [w.get('height', 2.4) for w in walls if 'height' in w]
                            room_height = max(heights) if heights else 2.4
                            
                            # ===== 窓を追加モード =====
                            # デバッグが必要なため、詳細ログはデフォルトで展開表示する
                            with st.expander("🔍 窓追加処理の詳細ログ", expanded=True):
                                total_added_count = 0
                                window_details = []
                
                                for rect_idx, (p1, p2) in enumerate(target_rects):
                                    st.markdown(f"---\n\n**窓#{rect_idx+1}の処理:**")
                                    
                                    # この窓のパラメータを取得
                                    if rect_idx < len(window_params_list):
                                        window_param = window_params_list[rect_idx]
                                        window_height_mm = window_param.get('height_mm', 1200)
                                        base_height_mm = window_param.get('base_mm', 900)
                                        window_model = window_param.get('model', None)
                                        
                                        window_height = float(window_height_mm) / 1000.0
                                        base_height = float(base_height_mm) / 1000.0
                                        
                                        st.info(f"📝 型番: {window_model if window_model and window_model != 'カスタム（手入力）' else 'カスタム'}, "
                                               f"高さ={window_height}m ({window_height_mm}mm), "
                                               f"床から={base_height}m ({base_height_mm}mm)")
                                    else:
                                        st.error(f"⚠️ 窓#{rect_idx+1}のパラメータが見つかりません")
                                        continue
                                    
                                    rect = {
                                        'left': min(p1[0], p2[0]),
                                        'top': min(p1[1], p2[1]),
                                        'width': abs(p2[0] - p1[0]),
                                        'height': abs(p2[1] - p1[1])
                                    }
                                
                                    # 四角形内に端点がある壁線を抽出（窓追加モード：端点2つだけを囲めばOK）
                                    # デバッグモードで詳細情報を取得
                                    walls_in_rect, debug_info = _filter_walls_by_endpoints_in_rect(
                                        updated_json['walls'], rect, scale, margin, img_height, min_x, min_y, max_x, max_y, 
                                        tolerance=0, debug=True
                                    )
                                    
                                    # デバッグ情報はUI表示を控え、セッションログへ出力
                                    try:
                                        append_debug(f"Window rect #{rect_idx+1}: coords=({p1},{p2}), walls_hit_count={len(walls_in_rect)}")
                                        append_debug(f"Window rect coords: p1={p1}, p2={p2}")
                                        for info in debug_info:
                                            append_debug(f"Window rect debug: {info}")
                                    except Exception:
                                        pass
                                    
                                    # 全ての壁のIDリストも表示（参考用）
                                    all_wall_ids = [w.get('id', '?') for w in updated_json['walls']]
                                    st.write(f"**全壁ID一覧:** {all_wall_ids[:20]}{'...' if len(all_wall_ids) > 20 else ''} (合計{len(all_wall_ids)}本)")
                                
                                    st.write(f"**選択範囲内の壁:** {len(walls_in_rect)}本")
                                    if walls_in_rect:
                                        st.write(f"検出された壁ID: {[w['id'] for w in walls_in_rect]}")
                                    # フォールバック: 端点で複数検出された場合、角度フィルタで2本に絞れるならそれを使う
                                    if len(walls_in_rect) != 2 and len(walls_in_rect) >= 2:
                                        try:
                                            angle_threshold_preview = 30.0
                                            angles = [math.radians(_wall_angle_deg(w)) for w in walls_in_rect]
                                            sx = sum(math.cos(a) for a in angles) if angles else 0
                                            sy = sum(math.sin(a) for a in angles) if angles else 0
                                            if sx == 0 and sy == 0:
                                                avg_angle = 0.0
                                            else:
                                                avg_angle = math.degrees(math.atan2(sy, sx))
                                            kept = [w for w in walls_in_rect if _angle_diff_deg(_wall_angle_deg(w), avg_angle) < angle_threshold_preview]
                                            if len(kept) == 2:
                                                try:
                                                    append_debug(f"Window execution: angle-filtered walls from {len(walls_in_rect)} to 2: ids={[w.get('id') for w in kept]}, avg_angle={avg_angle}")
                                                except Exception:
                                                    pass
                                                walls_in_rect = kept
                                                # 表示も更新しておく
                                                st.write(f"検出された壁ID(フィルタ後): {[w['id'] for w in walls_in_rect]}")
                                        except Exception:
                                            pass
                                
                                    if len(walls_in_rect) == 2:
                                        # 2本の壁の間に床側と天井側の壁を追加
                                        st.success(f"✅ 2本の壁を検出、窓追加処理を実行します")
                                        st.write(f"**デバッグ:** window_height={window_height}m ({window_height_mm}mm), base_height={base_height}m ({base_height_mm}mm), room_height={room_height}m")
                                        st.write(f"**計算:** ceiling_height = {room_height} - ({base_height} + {window_height}) = {room_height - (base_height + window_height)}m")
                                        updated_json, added_walls = add_window_walls(
                                            updated_json,
                                            walls_in_rect[0],
                                            walls_in_rect[1],
                                            window_height,
                                            base_height,
                                            room_height,
                                            window_model if window_model != 'カスタム（手入力）' else None,
                                            window_height_mm
                                        )
                                        total_added_count += len(added_walls)
                                        #st.success(f"✅ {len(added_walls)}本の壁を追加しました（ID: {[w['id'] for w in added_walls]}）")
                                        
                                        # 追加した壁の詳細を表示
                                        #for aw in added_walls:
                                        #    st.write(f"  追加壁ID#{aw['id']}: height={aw.get('height')}m ({aw.get('height')*1000:.0f}mm), "
                                        #            f"base_height={aw.get('base_height')}m ({aw.get('base_height')*1000:.0f}mm)")
                                        
                                        # 追加した壁のIDを記録（赤色表示用）
                                        added_wall_ids.extend([w['id'] for w in added_walls])
                                    
                                        color_name = ["赤", "緑", "青", "黄", "マゼンタ", "シアン"][rect_idx % 6]
                                        window_details.append({
                                            'rect_idx': rect_idx,
                                            'color_name': color_name,
                                            'wall_ids': [w['id'] for w in added_walls],
                                            'window_height': window_height,
                                            'window_height_mm': window_height_mm,
                                            'window_model': window_model if window_model != 'カスタム（手入力）' else None,
                                            'base_height': base_height,
                                            'base_height_mm': base_height_mm
                                        })
                                    elif len(walls_in_rect) < 2:
                                        try:
                                            append_debug(f"Window rect #{rect_idx+1} skipped during execution: found {len(walls_in_rect)} walls")
                                        except Exception:
                                            pass
                                        st.warning(f"⚠️ 四角形#{rect_idx+1}: 2本の壁が必要ですが、{len(walls_in_rect)}本しか見つかりません")
                                    else:
                                        st.warning(f"⚠️ 四角形#{rect_idx+1}: 2本の壁を選択してください（{len(walls_in_rect)}本選択されています）")
                
                                #if total_added_count > 0:
                                #    st.success(f"✅✅ 合計 {total_added_count} 本の壁を追加しました（窓{len(window_details)}箇所）")
                                
                                #    # 追加詳細を表示
                                #    st.markdown("**窓追加結果:**")
                                #    for detail in window_details:
                                #        st.write(
                                #            f"#{detail['rect_idx']+1}（{detail['color_name']}）: "
                                #            f"壁({detail['wall_ids'][0]}, {detail['wall_ids'][1]}) を追加 - "
                                #            f"窓高さ: {detail['window_height']}m ({detail.get('window_height_mm', int(detail['window_height']*1000))}mm), 床から: {detail['base_height']}m ({int(detail.get('base_height_mm', detail['base_height']*1000))}mm)"
                                #        )
                                #else:
                                #    st.warning("⚠️ 追加可能な窓が見つかりません")
                            
                            # 一時ファイルに保存
                            temp_json_path = Path(st.session_state.out_dir) / "walls_3d_edited.json"
                            with open(temp_json_path, 'w', encoding='utf-8') as f:
                                json.dump(updated_json, f, indent=2, ensure_ascii=False)
                            
                            # 再可視化（元の変換と同じスケールを使用）
                            # 追加した壁を赤色で表示
                            temp_viz_path = Path(st.session_state.out_dir) / "visualization_edited.png"
                            visualize_3d_walls(str(temp_json_path), str(temp_viz_path), scale=int(viz_scale), highlight_wall_ids=added_wall_ids, wall_color=(0, 0, 0), bg_color=(255, 255, 255))
                        
                            # 3Dビューア生成
                            temp_viewer_path = Path(st.session_state.out_dir) / "viewer_3d_edited.html"
                            _generate_3d_viewer_html(temp_json_path, temp_viewer_path)
                        
                            # 窓追加モードは自動保存
                            # セッション状態を更新（JSON・画像・3Dビューア）
                            st.session_state.json_bytes = temp_json_path.read_bytes()
                            st.session_state.json_name = "walls_3d_edited.json"
                            st.session_state.viz_bytes = temp_viz_path.read_bytes()
                            
                            # 3DビューアHTMLも更新
                            st.session_state.viewer_html_bytes = temp_viewer_path.read_bytes()
                            st.session_state.viewer_html_name = temp_viewer_path.name
                            
                            # 編集状態を完全にクリア（統一関数を使用）
                            _reset_selection_state()
                            st.session_state.reset_flag = False  # このフラグだけはFalseに設定
                            
                            st.success("✅ 窓追加完了！自動保存しました。さらに編集を続けることができます。")
                            time.sleep(0.5)
                            st.rerun()
                    
                        except Exception as e:
                            st.error(f"エラーが発生しました: {e}")
                            import traceback
                            st.code(traceback.format_exc())
                
                # 処理トリガーのチェック（ボタン表示なし、実行フラグのみ）
                should_execute = False
                
                if edit_mode == "線を結合" and st.session_state.get('merge_walls_to_process'):
                    # 前回のrerunで保存された壁を処理
                    should_execute = True
                elif edit_mode == "窓を追加" and st.session_state.get('window_walls_to_process'):
                    # 前回のrerunで保存された壁を処理
                    should_execute = True
                elif edit_mode == "線を削除" and st.session_state.get('delete_walls_to_process'):
                    # 前回のrerunで保存された壁を処理
                    should_execute = True
                elif edit_mode == "線を追加" and st.session_state.get('add_line_execute'):
                    # 線を追加モードの実行
                    st.session_state.add_line_execute = False
                    should_execute = True
                elif edit_mode == "オブジェクトを配置" and st.session_state.get('execute_furniture_placement'):
                    st.session_state.execute_furniture_placement = False
                    should_execute = True
                elif edit_mode == "階段を配置" and st.session_state.get('execute_stair_placement'):
                    st.session_state.execute_stair_placement = False
                    should_execute = True
                
                if should_execute:
                    try:
                        append_debug(f"should_execute=True, edit_mode={edit_mode}")
                    except:
                        pass
                    try:
                        # 処理対象の四角形リストを作成（確定済み選択 + 現在選択中の2点）
                        # 線を結合モードの場合は使用しない
                        # 窓を追加モードでクリック選択の場合も使用しない
                        # 線を削除モードもクリック選択なので使用しない
                        if edit_mode == "線を結合":
                            target_rects = []  # 線を結合モードでは不使用
                        elif edit_mode == "線を削除":
                            target_rects = []  # 線を削除モードでは不使用（クリック選択）
                        elif edit_mode == "窓を追加" and st.session_state.get('window_walls_to_process'):
                            target_rects = []  # 窓を追加モード（クリック選択）では不使用
                        else:
                            target_rects = list(st.session_state.rect_coords_list)
                            if len(st.session_state.rect_coords) == 2:
                                target_rects.append(tuple(st.session_state.rect_coords))
                        
                        try:
                            append_debug(f"target_rects生成完了: count={len(target_rects)}, edit_mode={edit_mode}")
                        except:
                            pass
                        
                        # JSONデータを読み込み
                        json_data = json.loads(st.session_state.json_bytes.decode("utf-8"))
                        walls = json_data['walls']
                        
                        # 可視化画像のパラメータを取得
                        all_x = [w['start'][0] for w in walls] + [w['end'][0] for w in walls]
                        all_y = [w['start'][1] for w in walls] + [w['end'][1] for w in walls]
                        min_x, max_x = min(all_x), max(all_x)
                        min_y, max_y = min(all_y), max(all_y)
                        
                        scale = int(viz_scale)
                        margin = 50
                        img_width = int((max_x - min_x) * scale) + 2 * margin
                        img_height = int((max_y - min_y) * scale) + 2 * margin
                        
                        # 編集前の画像を保存（比較用）
                        original_viz_bytes = st.session_state.viz_bytes
                        
                        # 元データを保護するためディープコピー
                        import copy
                        original_json_data = copy.deepcopy(json_data)
                        updated_json = json_data
                        
                        # 追加した壁のID（窓追加モードで使用）
                        added_wall_ids = []
                        
                        # 各モード用の変数を事前初期化
                        total_merged_count = 0
                        merge_details = []
                        total_added_count = 0
                        add_details = []
                        total_deleted_count = 0
                        delete_details = []
                        total_floor_count = 0
                        floor_details = []
                        
                        if edit_mode == "オブジェクトを配置":
                            # ===== オブジェクトを配置モード =====
                            # セッションステートから家具パラメータを取得
                            furniture_params = st.session_state.get('furniture_params', {})
                            height_option = furniture_params.get('height_option', '30cm')
                            color_option = furniture_params.get('color_option', 'ダーク')
                            
                            # 高さオプションの取得
                            if height_option == "天井合わせ":
                                heights = [w.get('height', 2.4) for w in walls if 'height' in w]
                                furniture_height = max(heights) if heights else 2.4
                            else:
                                furniture_height = FURNITURE_HEIGHT_OPTIONS.get(height_option, 0.3)
                            
                            # 各四角形をループして処理
                            for rect_idx, (p1, p2) in enumerate(target_rects):
                                # 四角形範囲をメートル座標に変換
                                x_start, y_start, width, depth = _snap_to_grid(
                                    (p1[0], p1[1], p2[0], p2[1]),
                                    json_data,
                                    scale
                                )
                                
                                # 家具を追加
                                updated_json = _add_furniture_to_json(
                                    updated_json,
                                    furniture_height,
                                    color_option,
                                    x_start,
                                    y_start,
                                    width,
                                    depth
                                )
                            
                            # 自動保存: オブジェクト配置結果を JSON/可視化/3Dビューアに反映
                            try:
                                temp_json_path = Path(st.session_state.out_dir) / "walls_3d_edited.json"
                                with open(temp_json_path, 'w', encoding='utf-8') as f:
                                    json.dump(updated_json, f, ensure_ascii=False, indent=2)

                                temp_viz_path = Path(st.session_state.out_dir) / "visualization_edited.png"
                                visualize_3d_walls(str(temp_json_path), str(temp_viz_path), scale=int(viz_scale), highlight_wall_ids=added_wall_ids, wall_color=(0, 0, 0), bg_color=(255, 255, 255))

                                temp_viewer_path = Path(st.session_state.out_dir) / "viewer_3d_edited.html"
                                _generate_3d_viewer_html(temp_json_path, temp_viewer_path)

                                # セッションに保存して UI 上でダウンロード可能にする
                                st.session_state.json_bytes = temp_json_path.read_bytes()
                                st.session_state.json_name = temp_json_path.name
                                st.session_state.viz_bytes = temp_viz_path.read_bytes()
                                st.session_state.viewer_html_bytes = temp_viewer_path.read_bytes()
                                st.session_state.viewer_html_name = temp_viewer_path.name

                                # 選択状態をクリア（統一関数を使用）
                                _reset_selection_state()
                            except Exception as e:
                                st.error(f"保存エラー: {e}")
                            
                        elif edit_mode == "階段を配置":
                            # ===== 階段を配置モード =====
                            # 選択範囲がない場合のエラーチェック
                            if len(target_rects) == 0:
                                st.error("❌ 階段配置範囲が選択されていません。画像上で2点をクリックして範囲を指定してください。")
                                # 処理を中断せず、エラー表示のみ
                                st.session_state.execute_stair_placement = False
                            else:
                                # セッションステートから階段パターンを取得
                                stair_pattern_key = st.session_state.get('selected_stair_pattern', 'コの字_時計回り_北')
                                stair_pattern = STAIR_PATTERNS.get(stair_pattern_key, STAIR_PATTERNS['コの字_時計回り_北'])
                                
                                # 各四角形（階段配置範囲）をループして処理
                                for rect_idx, (p1, p2) in enumerate(target_rects):
                                    # ピクセル座標→メートル座標変換（_snap_to_gridと同じロジック）
                                    x_min_px = min(p1[0], p2[0])
                                    x_max_px = max(p1[0], p2[0])
                                    y_min_px = min(p1[1], p2[1])
                                    y_max_px = max(p1[1], p2[1])
                                    
                                    # 左下隅の座標を計算（Y軸は反転するため、y_max_pxを使用）
                                    base_x = (x_min_px - margin) / scale + min_x
                                    base_y = (img_height - y_max_px - margin) / scale + min_y
                                    
                                    # 赤枠のサイズをメートル単位で計算
                                    rect_width_m = (x_max_px - x_min_px) / scale
                                    rect_height_m = (y_max_px - y_min_px) / scale
                                    
                                    # JSONに階段データを追加
                                    if 'stairs' not in updated_json:
                                        updated_json['stairs'] = []
                                    
                                    # 各ステップを追加（パターン定義のx_len, y_lenを直接使用）
                                    for step in stair_pattern['steps']:
                                        
                                        # パターン定義のx_len, y_lenを使用してサイズを計算
                                        # x_len, y_lenは0-1の正規化座標なので、実際の矩形サイズで掛け算
                                        width_m = rect_width_m * step['x_len']
                                        depth_m = rect_height_m * step['y_len']
                                        height_m = step['z_len']
                                        rotation = 0  # 全て同じ方向
                                        
                                        # 位置計算：パターン定義のx, yをそのまま使用
                                        # x, yは矩形内の正規化座標（0-1）なので、実際の矩形サイズで掛け算
                                        # 階段の中心座標を計算（Three.jsのBoxGeometryは中心基準）
                                        pos_x = base_x + step['x'] * rect_width_m + width_m / 2
                                        pos_y = base_y + step['y'] * rect_height_m + depth_m / 2

                                        
                                        # positionを中心座標として設定（Three.jsのBoxGeometryは中心基準）
                                        stair_data = {
                                            'name': f"{step['name']}_rect{rect_idx+1}",
                                            'position': [
                                                round(pos_x, 3),
                                                round(pos_y, 3),
                                                round(step['z'], 3)
                                            ],
                                            'size': [
                                                round(width_m, 3),
                                                round(depth_m, 3),
                                                round(height_m, 3)
                                            ],
                                            'rotation': 0,  # 全て同じ方向
                                            'color': 'Tan',  # 床と同じ色
                                            'pattern': stair_pattern_key
                                        }
                                        updated_json['stairs'].append(stair_data)
                            
                                # 自動保存: 階段配置結果を JSON/可視化/3Dビューアに反映
                                try:
                                    stair_count = len(updated_json.get('stairs', []))
                                    
                                    temp_json_path = Path(st.session_state.out_dir) / "walls_3d_edited.json"
                                    with open(temp_json_path, 'w', encoding='utf-8') as f:
                                        json.dump(updated_json, f, ensure_ascii=False, indent=2)

                                    # 階段配置では壁を追加しないため、highlight_wall_idsは空リスト
                                    temp_viz_path = Path(st.session_state.out_dir) / "visualization_edited.png"
                                    visualize_3d_walls(str(temp_json_path), str(temp_viz_path), scale=int(viz_scale), highlight_wall_ids=[], wall_color=(0, 0, 0), bg_color=(255, 255, 255))

                                    temp_viewer_path = Path(st.session_state.out_dir) / "viewer_3d_edited.html"
                                    _generate_3d_viewer_html(temp_json_path, temp_viewer_path)

                                    # セッションに保存して UI 上でダウンロード可能にする
                                    st.session_state.json_bytes = temp_json_path.read_bytes()
                                    st.session_state.json_name = temp_json_path.name
                                    st.session_state.viz_bytes = temp_viz_path.read_bytes()
                                    st.session_state.viewer_html_bytes = temp_viewer_path.read_bytes()
                                    st.session_state.viewer_html_name = temp_viewer_path.name

                                    # 選択状態をクリア（統一関数を使用）
                                    _reset_selection_state()
                                    st.session_state.last_click = None
                                    st.session_state.execute_stair_placement = False
                                    st.session_state.selected_stair_pattern = None
                                    
                                    # 成功メッセージ
                                    st.success(f"✅ 階段を{stair_count}ステップ配置しました！")
                                    
                                    # 画面を再描画して更新を反映
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"❌ 階段配置エラー: {e}")
                                    import traceback
                                    st.error(traceback.format_exc())
                                    try:
                                        append_debug(f"エラー発生: {e}")
                                        append_debug(f"トレースバック: {traceback.format_exc()}")
                                    except:
                                        pass
                            
                        elif edit_mode == "線を結合":
                            # ===== 線を結合モード（複数ペア一括対応） =====
                            # セッションに保存された壁を使用（ボタンクリック時に保存済み）
                            total_merged_count = 0
                            merge_details = []
                            
                            if st.session_state.get('merge_walls_to_process'):
                                # セッションから壁リストを取得
                                walls_list = st.session_state.merge_walls_to_process
                                
                                # 処理完了後にセッションから削除
                                del st.session_state.merge_walls_to_process
                                
                                # 2本ずつペアにして処理
                                merge_count = len(walls_list) // 2
                                success_count = 0
                                
                                for pair_idx in range(merge_count):
                                    wall1 = walls_list[pair_idx * 2]
                                    wall2 = walls_list[pair_idx * 2 + 1]
                                    
                                    try:
                                        append_debug(f"Merge {pair_idx + 1} started (click selection): wall1_id={wall1.get('id')}, wall2_id={wall2.get('id')}")
                                    except Exception:
                                        pass
                                    
                                    # クリック選択した2本の壁を直接結合処理
                                    walls_to_use = [wall1, wall2]
                                    selected_walls = [wall1, wall2]
                                    
                                    # 結合候補を探す
                                    merge_angle_threshold = 30
                                    candidates = _find_mergeable_walls(
                                        walls_to_use,
                                        distance_threshold=distance_threshold,
                                        angle_threshold=merge_angle_threshold
                                    )
                                    
                                    # フォールバック: 候補が見つからなければ閾値を緩めて再探索
                                    if not candidates:
                                        try:
                                            fallback_dist = max(distance_threshold * 2, 0.5)
                                            fallback_angle = max(merge_angle_threshold * 2, 45)
                                            candidates = _find_mergeable_walls(
                                                walls_to_use,
                                                distance_threshold=fallback_dist,
                                                angle_threshold=fallback_angle
                                            )
                                            if candidates:
                                                append_debug(f"Merge {pair_idx + 1}: Fallback candidates found")
                                        except Exception:
                                            pass
                                    
                                    # 最終フォールバック: それでも見つからない場合、強制的に候補を作成
                                    if not candidates:
                                        try:
                                            endpoints1 = [selected_walls[0]['start'], selected_walls[0]['end']]
                                            endpoints2 = [selected_walls[1]['start'], selected_walls[1]['end']]
                                            min_dist = None
                                            min_pair = None
                                            for p1 in endpoints1:
                                                for p2 in endpoints2:
                                                    d = _calc_distance(p1, p2)
                                                    if min_dist is None or d < min_dist:
                                                        min_dist = d
                                                        min_pair = (p1, p2)
                                            
                                            angle_diff_sel = _calc_angle_diff(selected_walls[0], selected_walls[1])
                                            
                                            # 接続タイプを決定
                                            p1, p2 = min_pair
                                            w1 = selected_walls[0]
                                            w2 = selected_walls[1]
                                            
                                            if p1 == w1['end'] and p2 == w2['start']:
                                                conn = 'end-start'
                                                new_start = w1['start']
                                                new_end = w2['end']
                                            elif p1 == w1['end'] and p2 == w2['end']:
                                                conn = 'end-end'
                                                new_start = w1['start']
                                                new_end = w2['start']
                                            elif p1 == w1['start'] and p2 == w2['start']:
                                                conn = 'start-start'
                                                new_start = w1['end']
                                                new_end = w2['end']
                                            elif p1 == w1['start'] and p2 == w2['end']:
                                                conn = 'start-end'
                                                new_start = w1['end']
                                                new_end = w2['start']
                                            else:
                                                conn = 'end-start'
                                                new_start = w1['start']
                                                new_end = w2['end']
                                            
                                            forced_candidate = {
                                                'wall1': w1,
                                                'wall2': w2,
                                                'is_chain': False,
                                                'distance': min_dist,
                                                'angle_diff': angle_diff_sel,
                                                'connection': conn,
                                                'new_start': new_start,
                                                'new_end': new_end,
                                                'confidence': 0.0
                                            }
                                            candidates = [forced_candidate]
                                            append_debug(f"Merge {pair_idx + 1}: Forced candidate created: {w1.get('id')} + {w2.get('id')}")
                                        except Exception as e:
                                            append_debug(f"Merge {pair_idx + 1}: Exception in forced candidate creation: {e}")
                                            pass
                                    
                                    # 結合実行
                                    if candidates:
                                        top_candidate = candidates[0]
                                        try:
                                            updated_json = _merge_walls_in_json(updated_json, candidates[:1])
                                            total_merged_count += 1
                                            success_count += 1
                                            append_debug(f"Merge {pair_idx + 1}: Successfully merged: {top_candidate.get('wall1',{}).get('id')} + {top_candidate.get('wall2',{}).get('id')}")
                                            
                                            merge_details.append({
                                                'rect_idx': pair_idx,
                                                'color_name': f'結合{pair_idx + 1}',
                                                'is_chain': False,
                                                'walls': [wall1['id'], wall2['id']],
                                                'distance': top_candidate['distance'],
                                                'direction': 'クリック選択',
                                                'deleted_walls': []
                                            })
                                        except Exception as e:
                                            append_debug(f"Merge {pair_idx + 1}: Error: {e}")
                                    else:
                                        append_debug(f"Merge {pair_idx + 1}: No candidates found")
                                
                                # すべての結合が完了したら選択状態をクリア
                                _reset_selection_state()
                                
                                # クリック選択処理を完了したので、四角形ベース処理はスキップ
                                # （クリック選択モードでは四角形ベース処理は不要）
                            
                            else:
                                # 以下、既存の四角形ベース処理（削除予定 - 後方互換のため残す）
                                for rect_idx, (p1, p2) in enumerate(target_rects):
                                    rect = {
                                        'left': min(p1[0], p2[0]),
                                        'top': min(p1[1], p2[1]),
                                        'width': abs(p2[0] - p1[0]),
                                        'height': abs(p2[1] - p1[1])
                                    }
                                    try:
                                        append_debug(f"Merge started: rect_idx={rect_idx+1}, rect={rect}")
                                    except Exception:
                                        pass
                                
                                    # 選択範囲内の壁線を抽出
                                    # スケール校正版と同様に「完全に含まれる」判定をまず試す（端点ベース）
                                    walls_in_selection = _filter_walls_strictly_in_rect(
                                        updated_json['walls'], rect, scale, margin, img_height, min_x, min_y, max_x, max_y
                                    )
                                    # 端点ベースで何も見つからなければ、交差/近接ベースでフォールバック（これを無効にする場合は削除）
                                    if len(walls_in_selection) == 0:
                                        walls_in_selection = [
                                            wall for wall in updated_json['walls']
                                            if _wall_in_rect(wall, rect, scale, margin, img_height, min_x, min_y, max_x, max_y)
                                        ]
                                    try:
                                        append_debug(f"walls_in_selection ids: {[w.get('id') for w in walls_in_selection]} (count={len(walls_in_selection)})")
                                    except Exception:
                                        pass

                                    # プレビューでフィルタ済みIDがセッションに保存されている場合、
                                    # 四角形が一致すれば execution 側の検出集合をプレビューのフィルタ済み集合に合わせる。
                                    try:
                                        last_filtered = st.session_state.get('last_preview_filtered_ids')
                                        last_rect = st.session_state.get('last_preview_rect')
                                        if last_filtered and last_rect:
                                            if (abs(last_rect.get('left',0) - rect.get('left',0)) < 1 and
                                                abs(last_rect.get('top',0) - rect.get('top',0)) < 1 and
                                                abs(last_rect.get('width',0) - rect.get('width',0)) < 1 and
                                                abs(last_rect.get('height',0) - rect.get('height',0)) < 1):
                                                # updated_json の walls から該当IDを抽出（四角形外でも preview が見ていたIDを優先）
                                                id_set = set(last_filtered)
                                                walls_in_selection = [w for w in updated_json['walls'] if w.get('id') in id_set]
                                                try:
                                                    st.write(f"🔧 プレビューのフィルタ済みIDを優先して walls_in_selection を置換しました: {list(id_set)}")
                                                except Exception:
                                                    pass
                                                try:
                                                    append_debug(f"Applied preview filtered ids as walls_in_selection: {list(id_set)}")
                                                except Exception:
                                                    pass
                                    except Exception:
                                        pass
                                
                                    # まず、プレビューで選ばれたペアがあるかを確認し、四角形が一致すればそれを優先する
                                    walls_to_use = None
                                    try:
                                        last_pair = st.session_state.get('last_preview_pair')
                                        last_rect = st.session_state.get('last_preview_rect')
                                        if last_pair and last_rect:
                                            # rect と同じなら preview のペアを利用
                                            if (abs(last_rect.get('left',0) - rect.get('left',0)) < 1 and
                                                abs(last_rect.get('top',0) - rect.get('top',0)) < 1 and
                                                abs(last_rect.get('width',0) - rect.get('width',0)) < 1 and
                                                abs(last_rect.get('height',0) - rect.get('height',0)) < 1):
                                                # updated_json の walls から id を探して walls_to_use を構築
                                                id_set = set(last_pair)
                                                walls_to_use = [w for w in walls_in_selection if w.get('id') in id_set]
                                                if len(walls_to_use) != 2:
                                                    walls_to_use = None
                                    except Exception:
                                        walls_to_use = None

                                    # プレビュー優先が使えない場合は従来通り角度フィルタを試す
                                    if walls_to_use is None:
                                        filtered_by_angle = None
                                        try:
                                            angles = [math.radians(_wall_angle_deg(w)) for w in walls_in_selection]
                                            sx = sum(math.cos(a) for a in angles)
                                            sy = sum(math.sin(a) for a in angles)
                                            if sx == 0 and sy == 0:
                                                avg_angle = 0.0
                                            else:
                                                avg_angle = math.degrees(math.atan2(sy, sx))

                                            angle_threshold = 30.0
                                            kept = [w for w in walls_in_selection if _angle_diff_deg(_wall_angle_deg(w), avg_angle) < angle_threshold]
                                            if len(kept) >= 2:
                                                filtered_by_angle = kept
                                        except Exception:
                                            filtered_by_angle = None

                                        if filtered_by_angle is not None:
                                            walls_to_use = filtered_by_angle
                                        else:
                                            walls_to_use = walls_in_selection

                                    try:
                                        append_debug(f"walls_to_use ids: {[w.get('id') for w in walls_to_use]} (count={len(walls_to_use)})")
                                    except Exception:
                                        pass

                                    # デバッグログにも追加
                                    try:
                                        wall_info = f"選択範囲内の壁: {len(walls_to_use)}本"
                                        st.write(f"**{wall_info}**")
                                        append_debug(wall_info)
                                        if walls_to_use:
                                            wall_ids_in_selection = [w['id'] for w in walls_to_use]
                                            wall_display = ", ".join([f"壁({wid})" for wid in wall_ids_in_selection])
                                            wall_list_info = f"壁: {wall_display}"
                                            st.write(wall_list_info)
                                            append_debug(wall_list_info)
                                    except Exception:
                                        pass
                                    
                                    if len(walls_to_use) >= 2:
                                        # 複数線が選択されている場合、方向を判定して最も離れた2本のペアのみを結合
                                        # 四角形の幅と高さから方向を判定
                                        rect_width = abs(p2[0] - p1[0])
                                        rect_height = abs(p2[1] - p1[1])
                                    
                                        if rect_width > rect_height:
                                            # X方向：x座標で最も離れた2本を選択
                                            walls_by_x = sorted(walls_to_use, 
                                                                key=lambda w: min(w['start'][0], w['end'][0]))
                                            leftmost_wall = walls_by_x[0]
                                            rightmost_wall = walls_by_x[-1]
                                        
                                            # 2本だけを結合候補として抽出
                                            selected_walls = [leftmost_wall, rightmost_wall]
                                            direction = "X方向"
                                        else:
                                            # Y方向：y座標で最も離れた2本を選択
                                            walls_by_y = sorted(walls_to_use,
                                                            key=lambda w: min(w['start'][1], w['end'][1]))
                                            bottom_wall = walls_by_y[0]
                                            top_wall = walls_by_y[-1]
                                        
                                            # 2本だけを結合候補として抽出
                                            selected_walls = [bottom_wall, top_wall]
                                            direction = "Y方向"
                                    
                                        # デバッグログにも追加
                                        try:
                                            direction_info = f"方向判定: {direction} (幅: {rect_width}px, 高さ: {rect_height}px)"
                                            merge_target_info = f"結合対象: 壁({selected_walls[0]['id']}) ← → 壁({selected_walls[1]['id']})"
                                            st.write(f"**{direction_info}**")
                                            st.write(f"**{merge_target_info}**")
                                            append_debug(direction_info)
                                            append_debug(merge_target_info)
                                        except Exception:
                                            pass
                                    
                                        # 結合候補を探す（選択された2本だけ）
                                        # 結合側の閾値はプレビューの角度フィルタと合わせて30度に緩和
                                        merge_angle_threshold = 30
                                        # 追加デバッグ: 選択集合内の全ペアについて最短端点距離と角度差を表示
                                        try:
                                            pair_debug = []
                                            for i, wa in enumerate(walls_to_use):
                                                for j, wb in enumerate(walls_to_use):
                                                    if i >= j:
                                                        continue
                                                    endpoints_a = [wa['start'], wa['end']]
                                                    endpoints_b = [wb['start'], wb['end']]
                                                    min_d = None
                                                    for pa in endpoints_a:
                                                        for pb in endpoints_b:
                                                            d = _calc_distance(pa, pb)
                                                            if min_d is None or d < min_d:
                                                                min_d = d
                                                    ang = _calc_angle_diff(wa, wb)
                                                    pair_debug.append({'wall1': wa.get('id'), 'wall2': wb.get('id'), 'min_endpoint_dist_m': round(min_d,4) if min_d is not None else None, 'angle_diff_deg': round(ang,2)})
                                            pair_debug_str = str(pair_debug)
                                            st.write('**デバッグ (全ペア距離/角度):**', pair_debug)
                                            try:
                                                append_debug(f"全ペア距離/角度: {pair_debug_str}")
                                            except Exception:
                                                pass
                                        except Exception:
                                            pass

                                        # チェーン検出を含めるため、選択された2本のみではなく
                                        # フィルタ済みの `walls_to_use` 全体を渡す。
                                        candidates = _find_mergeable_walls(
                                            walls_to_use,
                                            distance_threshold=distance_threshold,
                                            angle_threshold=merge_angle_threshold
                                        )

                                        # デバッグ情報: 選択した2本の角度差と最短端点距離を表示
                                        try:
                                            angle_diff_sel = _calc_angle_diff(selected_walls[0], selected_walls[1])
                                            # 最短端点距離を計算
                                            endpoints1 = [selected_walls[0]['start'], selected_walls[0]['end']]
                                            endpoints2 = [selected_walls[1]['start'], selected_walls[1]['end']]
                                            min_dist = min(_calc_distance(p1, p2) for p1 in endpoints1 for p2 in endpoints2)
                                            selected_wall_info = f"選択壁の角度差: {angle_diff_sel:.2f}度, 最短端点距離: {min_dist:.3f} m"
                                            st.write(f"**{selected_wall_info}**")
                                            try:
                                                append_debug(selected_wall_info)
                                            except Exception:
                                                pass
                                        except Exception:
                                            pass

                                        # 候補の詳細を常に表示（空でも明示）
                                        try:
                                            cand_list = []
                                            for c in candidates:
                                                if c.get('is_chain'):
                                                    cand_list.append({'type': 'chain', 'chain_length': c.get('chain_length'), 'distance': c.get('distance'), 'angle_diff': c.get('angle_diff'), 'confidence': c.get('confidence')})
                                                else:
                                                    cand_list.append({'type': 'pair', 'wall1': c.get('wall1', {}).get('id'), 'wall2': c.get('wall2', {}).get('id'), 'distance': c.get('distance'), 'angle_diff': c.get('angle_diff'), 'confidence': c.get('confidence')})
                                            cand_list_str = str(cand_list)
                                            st.write("**デバッグ (候補一覧):**", cand_list)
                                            try:
                                                append_debug(f"候補一覧: {cand_list_str}")
                                            except Exception:
                                                pass
                                        except Exception:
                                            pass

                                        # フォールバック: 候補が見つからなければ閾値を緩めて再探索
                                        if not candidates:
                                            try:
                                                fallback_dist = max(distance_threshold * 2, 0.5)
                                                fallback_angle = max(merge_angle_threshold * 2, 45)
                                                st.warning(f"候補が見つかりません。フォールバック閾値で再探索します (距離: {fallback_dist}m, 角度: {fallback_angle}°)")
                                                candidates_fb = _find_mergeable_walls(
                                                    selected_walls,
                                                    distance_threshold=fallback_dist,
                                                    angle_threshold=fallback_angle
                                                )
                                                cand_fb_list = []
                                                for c in candidates_fb:
                                                    if c.get('is_chain'):
                                                        cand_fb_list.append({'type': 'chain', 'chain_length': c.get('chain_length'), 'distance': c.get('distance'), 'angle_diff': c.get('angle_diff'), 'confidence': c.get('confidence')})
                                                    else:
                                                        cand_fb_list.append({'type': 'pair', 'wall1': c.get('wall1', {}).get('id'), 'wall2': c.get('wall2', {}).get('id'), 'distance': c.get('distance'), 'angle_diff': c.get('angle_diff'), 'confidence': c.get('confidence')})
                                                st.write("**デバッグ (フォールバック候補一覧):**", cand_fb_list)
                                                if candidates_fb:
                                                    candidates = candidates_fb
                                                    st.info("フォールバックで候補が見つかりました。結合を実行します。")
                                                    try:
                                                        append_debug(f"Fallback candidates: {cand_fb_list}")
                                                    except Exception:
                                                        pass
                                                else:
                                                    st.warning("フォールバックでも候補が見つかりませんでした。四角形選択や閾値を確認してください。")
                                            except Exception:
                                                pass

                                        # 追加: 2点選択時に候補が見つからない場合、周辺の壁を含めたチェーン検索を試みる
                                        if not candidates:
                                            try:
                                                # selected_walls が存在し、2本選択されている場合にのみ実行
                                                if 'selected_walls' in locals() and len(selected_walls) == 2:
                                                    # 参照角度と閾値
                                                    ref_angle = _wall_angle_deg(selected_walls[0])
                                                    angle_tol = merge_angle_threshold
                                                    # 周辺壁を収集（角度が近く、端点距離が近いもの）
                                                    neighborhood = []
                                                    for w in updated_json.get('walls', []):
                                                        try:
                                                            if _angle_diff_deg(_wall_angle_deg(w), ref_angle) < angle_tol:
                                                                endpoints_sel = [selected_walls[0]['start'], selected_walls[0]['end'], selected_walls[1]['start'], selected_walls[1]['end']]
                                                                endpoints_w = [w['start'], w['end']]
                                                                min_d = min(_calc_distance(p1, p2) for p1 in endpoints_sel for p2 in endpoints_w)
                                                                # 距離閾値は少し広めに設定（既定閾値の2倍または0.5m）
                                                                if min_d <= max(distance_threshold * 2, 0.5):
                                                                    neighborhood.append(w)
                                                        except Exception:
                                                            continue

                                                    if len(neighborhood) >= 2:
                                                        candidates_ext = _find_mergeable_walls(
                                                            neighborhood,
                                                            distance_threshold=distance_threshold,
                                                            angle_threshold=merge_angle_threshold
                                                        )
                                                        if candidates_ext:
                                                            candidates = candidates_ext
                                                            st.info('周辺壁を含めた拡張チェーン検索で候補を検出しました。')
                                                            try:
                                                                append_debug(f"Neighborhood-extended candidates found: count={len(candidates_ext)}")
                                                            except Exception:
                                                                pass
                                            except Exception:
                                                pass
                                        # 追加フォールバック: 2点選択で角度が近いが距離が大きい場合、小さめの閾値で自動強制候補を作成する
                                        if not candidates:
                                            try:
                                                if 'selected_walls' in locals() and len(selected_walls) == 2:
                                                    # 最短端点距離と角度差を計算
                                                    endpoints1 = [selected_walls[0]['start'], selected_walls[0]['end']]
                                                    endpoints2 = [selected_walls[1]['start'], selected_walls[1]['end']]
                                                    min_dist_tmp = min(_calc_distance(p1, p2) for p1 in endpoints1 for p2 in endpoints2)
                                                    angle_diff_tmp = _calc_angle_diff(selected_walls[0], selected_walls[1])
                                                    # 許容距離：ほぼ無制限にする（既定閾値の100倍）
                                                    extended_limit = distance_threshold * 100
                                                    if angle_diff_tmp <= merge_angle_threshold and min_dist_tmp <= extended_limit:
                                                        # 自動強制候補を作成
                                                        w1 = selected_walls[0]
                                                        w2 = selected_walls[1]
                                                        # 最短端点組合せから接続タイプを決定
                                                        min_pair = None
                                                        md = None
                                                        for p1 in endpoints1:
                                                            for p2 in endpoints2:
                                                                d = _calc_distance(p1, p2)
                                                                if md is None or d < md:
                                                                    md = d
                                                                    min_pair = (p1, p2)
                                                        p1p, p2p = min_pair
                                                        conn = 'end-start'
                                                        if p1p == w1.get('end') and p2p == w2.get('start'):
                                                            conn = 'end-start'
                                                        elif p1p == w1.get('end') and p2p == w2.get('end'):
                                                            conn = 'end-end'
                                                        elif p1p == w1.get('start') and p2p == w2.get('start'):
                                                            conn = 'start-start'
                                                        elif p1p == w1.get('start') and p2p == w2.get('end'):
                                                            conn = 'start-end'
                                                        # new_start/new_end を接続タイプに合わせて設定
                                                        if conn == 'end-start':
                                                            new_start = w1.get('start')
                                                            new_end = w2.get('end')
                                                        elif conn == 'end-end':
                                                            new_start = w1.get('start')
                                                            new_end = w2.get('start')
                                                        elif conn == 'start-start':
                                                            new_start = w1.get('end')
                                                            new_end = w2.get('end')
                                                        elif conn == 'start-end':
                                                            new_start = w1.get('end')
                                                            new_end = w2.get('start')
                                                        else:
                                                            new_start = None
                                                            new_end = None
                                                        forced_candidate_auto = {
                                                            'wall1': w1,
                                                            'wall2': w2,
                                                            'is_chain': False,
                                                            'distance': md,
                                                            'angle_diff': angle_diff_tmp,
                                                            'connection': conn,
                                                            'new_start': new_start,
                                                            'new_end': new_end,
                                                            'confidence': 0.0
                                                        }
                                                        candidates = [forced_candidate_auto]
                                                        st.info(f'自動フォールバックで強制候補を作成します（距離={md:.3f}m, 角度差={angle_diff_tmp:.2f}°）')
                                                        try:
                                                            append_debug(f"Auto-forced candidate applied: pair={w1.get('id')},{w2.get('id')}, min_dist={md}, angle_diff={angle_diff_tmp}")
                                                        except Exception:
                                                            pass
                                            except Exception:
                                                pass

                                        # 強制適用: プレビューで選ばれたペアがある場合、四角形が一致すれば候補が空でも強制的にペアを作成して結合する
                                        if not candidates:
                                            try:
                                                last_pair = st.session_state.get('last_preview_pair')
                                                last_rect = st.session_state.get('last_preview_rect')
                                                if last_pair:
                                                            # プレビューで指定されたペアが現在の選択と一致すれば
                                                            # 四角形の完全一致に依存せず強制適用する（ユーザがプレビューで選択した意図を尊重）
                                                            id_set = set(last_pair)
                                                            sel_ids = {selected_walls[0]['id'], selected_walls[1]['id']}
                                                            if id_set == sel_ids:
                                                                try:
                                                                    append_debug(f"Preview pair matches selected_walls (ignoring rect): pair={list(id_set)}")
                                                                except Exception:
                                                                    pass
                                                                # 最短端点距離と角度差を再計算
                                                                # （以下は従来の強制適用処理と同じ）
                                                        
                                                            # 最短端点距離と角度差を再計算
                                                            endpoints1 = [selected_walls[0]['start'], selected_walls[0]['end']]
                                                            endpoints2 = [selected_walls[1]['start'], selected_walls[1]['end']]
                                                            min_dist = None
                                                            min_pair = None
                                                            for p1 in endpoints1:
                                                                for p2 in endpoints2:
                                                                    d = _calc_distance(p1, p2)
                                                                    if min_dist is None or d < min_dist:
                                                                        min_dist = d
                                                                        min_pair = (p1, p2)

                                                            angle_diff_sel = _calc_angle_diff(selected_walls[0], selected_walls[1])

                                                            # 接続タイプを最短端点組合せから決定
                                                            conn = None
                                                            p1, p2 = min_pair
                                                            if p1 == selected_walls[0]['end'] and p2 == selected_walls[1]['start']:
                                                                conn = 'end-start'
                                                            elif p1 == selected_walls[0]['end'] and p2 == selected_walls[1]['end']:
                                                                conn = 'end-end'
                                                            elif p1 == selected_walls[0]['start'] and p2 == selected_walls[1]['start']:
                                                                conn = 'start-start'
                                                            elif p1 == selected_walls[0]['start'] and p2 == selected_walls[1]['end']:
                                                                conn = 'start-end'
                                                            else:
                                                                conn = 'end-start'

                                                            # new_start/new_end を接続タイプに合わせて設定
                                                            w1 = selected_walls[0]
                                                            w2 = selected_walls[1]
                                                            if conn == 'end-start':
                                                                new_start = w1.get('start')
                                                                new_end = w2.get('end')
                                                            elif conn == 'end-end':
                                                                new_start = w1.get('start')
                                                                new_end = w2.get('start')
                                                            elif conn == 'start-start':
                                                                new_start = w1.get('end')
                                                                new_end = w2.get('end')
                                                            elif conn == 'start-end':
                                                                new_start = w1.get('end')
                                                                new_end = w2.get('start')
                                                            else:
                                                                new_start = None
                                                                new_end = None

                                                            forced_candidate = {
                                                                'wall1': w1,
                                                                'wall2': w2,
                                                                'is_chain': False,
                                                                'distance': min_dist,
                                                                'angle_diff': angle_diff_sel,
                                                                'connection': conn,
                                                                'new_start': new_start,
                                                                'new_end': new_end,
                                                                'confidence': 0.0
                                                            }
                                                            candidates = [forced_candidate]
                                                            st.info('プレビュー選択ペアを強制適用して結合を試みます（距離閾値を超えています）。')
                                                            try:
                                                                append_debug(f"Forced candidate applied: pair={w1.get('id')},{w2.get('id')}, min_dist={min_dist}, angle_diff={angle_diff_sel}")
                                                            except Exception:
                                                                pass
                                            except Exception:
                                                pass
                                    
                                        if candidates:
                                            # 最有力候補の詳細情報を表示（デバッグ用）
                                            top_candidate = candidates[0]
                                            st.write(f"**検出されたペア：**")
                                            if top_candidate.get('is_chain', False):
                                                chain_wall_ids = [w['id'] for w in top_candidate['walls']]
                                                st.write(f"チェーン: {chain_wall_ids}")
                                            else:
                                                st.write(f"ペア: 壁#{top_candidate['wall1']['id']} + 壁#{top_candidate['wall2']['id']}")
                                        
                                            # 最有力候補で結合（エラー時は処理を中断して詳細を表示）
                                            try:
                                                updated_json = _merge_walls_in_json(updated_json, candidates[:1])
                                                total_merged_count += 1
                                                try:
                                                    if top_candidate.get('is_chain'):
                                                        append_debug(f"Merged chain: walls={ [w['id'] for w in top_candidate.get('walls',[])] }")
                                                    else:
                                                        append_debug(f"Merged pair: {top_candidate.get('wall1',{}).get('id')} + {top_candidate.get('wall2',{}).get('id')}, distance={top_candidate.get('distance')}, angle_diff={top_candidate.get('angle_diff')}")
                                                except Exception:
                                                    pass
                                            except Exception as e:
                                                try:
                                                    import traceback
                                                    tb = traceback.format_exc()
                                                except Exception:
                                                    tb = str(e)
                                                st.error(f"結合実行中にエラーが発生しました: {e}")
                                                st.error(f"トレースバック:\n{tb}")
                                                # 確実に処理を中断する（SystemExit を投げて上位の broad except に捕まらないようにする）
                                                import sys
                                                sys.exit(1)
                                        
                                            # 四角形内の他の不要な線分（中間線）を削除
                                            # 削除対象は、実際に選択・フィルタされた集合 `walls_to_use` を基準とする。
                                            # ただし、窓追加などで自動生成された壁（source=='window_added'）は削除対象から除外する。
                                            walls_to_delete = []
                                            try:
                                                basis_list = walls_to_use if walls_to_use is not None else walls_in_selection
                                                # マージ候補がチェーンかペアかで残すIDを決定
                                                keep_ids = set()
                                                try:
                                                    top_cand = candidates[0]
                                                    if top_cand.get('is_chain'):
                                                        # チェーンの最初の壁のみ残す（_merge_walls_in_json と整合）
                                                        keep_ids.add(top_cand['walls'][0]['id'])
                                                    else:
                                                        keep_ids.add(top_cand['wall1']['id'])
                                                except Exception:
                                                    # 候補情報が見つからない場合は選択2本を残す
                                                    keep_ids.add(selected_walls[0]['id'])
                                                    keep_ids.add(selected_walls[1]['id'])

                                                for wall in basis_list:
                                                    # 窓追加で生成された壁は保護する
                                                    try:
                                                        if wall.get('source') == 'window_added':
                                                            try:
                                                                append_debug(f"Protecting window-added wall from deletion: {wall.get('id')}")
                                                            except Exception:
                                                                pass
                                                            continue
                                                    except Exception:
                                                        pass
                                                    if wall['id'] not in keep_ids:
                                                        walls_to_delete.append(wall['id'])
                                            except Exception:
                                                # フォールバック: 以前の挙動に一致させるが、窓追加で生成された壁は削除しない
                                                for wall in walls_in_selection:
                                                    try:
                                                        if wall.get('source') == 'window_added':
                                                            continue
                                                    except Exception:
                                                        pass
                                                    if wall['id'] not in [selected_walls[0]['id'], selected_walls[1]['id']]:
                                                        walls_to_delete.append(wall['id'])
                                        
                                            if walls_to_delete:
                                                st.write(f"**削除対象の中間線:** 壁#{walls_to_delete}")
                                                updated_json = _delete_walls_in_json(updated_json, walls_to_delete)
                                        
                                            color_name = ["赤", "緑", "青", "黄", "マゼンタ", "シアン"][rect_idx % 6]
                                        
                                            # 結合詳細を記録
                                            merge_details.append({
                                                'rect_idx': rect_idx,
                                                'color_name': color_name,
                                                'is_chain': False,
                                                'walls': [selected_walls[0]['id'], selected_walls[1]['id']],
                                                'distance': top_candidate['distance'],
                                                'direction': direction,
                                                'deleted_walls': walls_to_delete
                                            })
                                        else:
                                            st.warning(f"⚠️ 四角形内の壁が接続されていません")
                                
                                    if total_merged_count > 0:
                                        # クリック選択の場合は組数を表示
                                        if st.session_state.get('edit_mode') == "線を結合" and len(merge_details) > 0 and merge_details[0].get('color_name', '').startswith('結合'):
                                            st.success(f"✅ 合計 {total_merged_count} 組の結合が完了しました")
                                        else:
                                            st.success(f"✅ 合計 {total_merged_count} 個の選択範囲で結合が完了しました")
                                    
                                        # 結合詳細を表示
                                        st.markdown("**結合結果:**")
                                        for detail in merge_details:
                                            result_text = (
                                                f"#{detail['rect_idx']+1}（{detail['color_name']}）: "
                                                f"壁({detail['walls'][0]}) ↔ 壁({detail['walls'][1]}) "
                                                f"({detail['direction']}) - "
                                                f"距離: {detail['distance']:.3f}m"
                                            )
                                            if detail.get('deleted_walls'):
                                                deleted_display = ", ".join([f"壁({wid})" for wid in detail['deleted_walls']])
                                                result_text += f" | 削除: {deleted_display}"
                                            st.write(result_text)
                                    else:
                                        st.warning("⚠️ 選択範囲内に結合可能な壁線が見つかりません")
                        
                        elif edit_mode == "窓を追加" and st.session_state.get('window_walls_to_process'):
                                    # ===== 窓を追加モード（クリック選択・複数窓対応） =====
                                    # セッションに保存された壁を使用（ボタンクリック時に保存済み）
                                    walls_list = st.session_state.window_walls_to_process
                                    params_list = st.session_state.get('window_click_params_list_to_process', [])
                                    
                                    window_count = len(walls_list) // 2
                                    
                                    st.markdown(f"### 🪟 窓追加処理（{window_count}組）")
                                    
                                    # 天井高さ（部屋の高さ）を取得
                                    heights = [w.get('height', 2.4) for w in walls if 'height' in w]
                                    room_height = max(heights) if heights else 2.4
                                    
                                    # 各窓ペアを処理
                                    total_windows_added = 0
                                    for window_idx in range(window_count):
                                        wall1 = walls_list[window_idx * 2]
                                        wall2 = walls_list[window_idx * 2 + 1]
                                        window_params = params_list[window_idx] if window_idx < len(params_list) else {}
                                        
                                        # パラメータを取得
                                        window_model = window_params.get('model')
                                        window_width_mm = window_params.get('width_mm', 1200)
                                        window_height_mm = window_params.get('height_mm', 1200)
                                        base_height_mm = window_params.get('base_mm', 900)
                                        
                                        window_height = float(window_height_mm) / 1000.0
                                        base_height = float(base_height_mm) / 1000.0
                                        
                                        st.markdown(f"#### 窓{window_idx + 1}")
                                        st.info(f"📝 型番: {window_model if window_model and window_model != 'カスタム（手入力）' else 'カスタム'}, "
                                               f"窓高さ={window_height}m ({window_height_mm}mm), "
                                               f"床から={base_height}m ({base_height_mm}mm)")
                                        
                                        # 選択された2本の壁の間に窓を追加
                                        try:
                                            updated_json, added_walls = add_window_walls(
                                                updated_json,
                                                wall1,
                                                wall2,
                                                window_height,
                                                base_height,
                                                room_height,
                                                window_model if window_model != 'カスタム（手入力）' else None,
                                                window_height_mm
                                            )
                                            
                                            added_wall_ids.extend([w['id'] for w in added_walls])
                                            #st.success(f"✅ {len(added_walls)}本の壁を追加しました（ID: {[w['id'] for w in added_walls]}）")
                                            
                                            # 追加した壁の詳細を表示
                                            #for aw in added_walls:
                                            #    st.write(f"  追加壁ID#{aw['id']}: height={aw.get('height')}m ({aw.get('height')*1000:.0f}mm), "
                                            #            f"base_height={aw.get('base_height')}m ({aw.get('base_height')*1000:.0f}mm)")
                                            
                                            total_windows_added += 1
                                        except Exception as e:
                                            st.error(f"窓{window_idx + 1}追加エラー: {e}")
                                            import traceback
                                            st.code(traceback.format_exc())
                                    
                                    # 処理成功後にセッションから削除
                                    if 'window_walls_to_process' in st.session_state:
                                        del st.session_state.window_walls_to_process
                                    if 'window_click_params_list_to_process' in st.session_state:
                                        del st.session_state.window_click_params_list_to_process
                                    if 'window_click_params_list' in st.session_state:
                                        del st.session_state.window_click_params_list
                                    
                                    if total_windows_added > 0:
                                        st.success(f"🎉 合計{total_windows_added}組の窓を追加しました！")
                        
                        elif edit_mode == "線を追加":
                            # ===== 線を追加モード =====
                            total_added_count = 0
                            add_details = []
                        
                            for rect_idx, (p1, p2) in enumerate(target_rects):
                                rect = {
                                    'left': min(p1[0], p2[0]),
                                    'top': min(p1[1], p2[1]),
                                    'width': abs(p2[0] - p1[0]),
                                    'height': abs(p2[1] - p1[1])
                                }
                            
                                # 選択範囲内の壁線を抽出
                                walls_in_selection = [
                                    wall for wall in updated_json['walls']
                                    if _wall_in_rect(wall, rect, scale, margin, img_height, min_x, min_y, max_x, max_y)
                                ]
                            
                                # 既存の全ての壁から平均高さを取得（デフォルト2.4m）
                                all_heights = [w.get('height', 2.4) for w in updated_json['walls'] if 'height' in w]
                                wall_height_to_use = sum(all_heights) / len(all_heights) if all_heights else 2.4
                            
                                # 線を追加（スケールをセッション状態から取得）
                                updated_json, direction, new_wall = _add_line_to_json(
                                    updated_json, p1, p2, wall_height=wall_height_to_use, scale=st.session_state.viz_scale
                                )
                                
                                total_added_count += 1
                                add_details.append({
                                    'rect_idx': rect_idx,
                                    'direction': direction,
                                    'wall_id': new_wall['id'],
                                    'length': new_wall['length']
                                })
                            
                            #if total_added_count > 0:
                            #    st.success(f"🎉 合計{total_added_count}本の壁を追加しました！")
                            #    for detail in add_details:
                            #        st.write(f"  壁ID#{detail['wall_id']}: 方向={detail['direction']}, 長さ={detail['length']:.2f}m")
                        
                        elif edit_mode == "線を削除":
                            # ===== 線を削除モード =====
                            total_deleted_count = 0
                            delete_details = []
                            walls_to_delete = []  # 削除対象の壁IDリスト
                            
                            # セッションに保存された壁を使用（ボタンクリック時に保存済み）
                            if st.session_state.get('delete_walls_to_process'):
                                # セッションから壁リストを取得
                                walls_list = st.session_state.delete_walls_to_process
                                
                                # 処理完了後にセッションから削除
                                del st.session_state.delete_walls_to_process
                                
                                # クリック選択された壁を削除
                                for wall in walls_list:
                                    walls_to_delete.append(wall['id'])
                                    delete_details.append({
                                        'method': 'クリック選択',
                                        'wall_id': wall['id']
                                    })
                                total_deleted_count = len(walls_to_delete)
                                
                                # 壁を削除
                                if len(walls_to_delete) > 0:
                                    updated_json = _delete_walls_in_json(updated_json, walls_to_delete)
                                
                                # 全体のリセットは後の共通処理で実行される
                            
                            # クリック選択された壁を削除（後方互換性のため残す）
                            elif len(st.session_state.selected_walls_for_delete) > 0:
                                for wall in st.session_state.selected_walls_for_delete:
                                    walls_to_delete.append(wall['id'])
                                    delete_details.append({
                                        'method': 'クリック選択',
                                        'wall_id': wall['id']
                                    })
                                total_deleted_count = len(walls_to_delete)
                                
                                # 壁を削除
                                if len(walls_to_delete) > 0:
                                    updated_json = _delete_walls_in_json(updated_json, walls_to_delete)
                                    # 削除成功後、選択リストをクリア（注：全体のリセットは後の共通処理で実行される）
                                    st.session_state.selected_walls_for_delete = []
                            
                            # 四角形ベースの削除（後方互換性のため残す）
                            for rect_idx, (p1, p2) in enumerate(target_rects):
                                rect = {
                                    'left': min(p1[0], p2[0]),
                                    'top': min(p1[1], p2[1]),
                                    'width': abs(p2[0] - p1[0]),
                                    'height': abs(p2[1] - p1[1])
                                }
                            
                                # 四角形内に完全に含まれる壁線を抽出
                                walls_in_rect = _filter_walls_strictly_in_rect(
                                    updated_json['walls'], rect, scale, margin, img_height, min_x, min_y, max_x, max_y
                                )
                            
                                if walls_in_rect:
                                    # 四角形内の壁をすべて削除対象に追加
                                    color_name = ["赤", "緑", "青", "黄", "マゼンタ", "シアン"][rect_idx % 6]
                                    for wall in walls_in_rect:
                                        if wall['id'] not in walls_to_delete:  # 重複を避ける
                                            walls_to_delete.append(wall['id'])
                                            delete_details.append({
                                                'rect_idx': rect_idx,
                                                'color_name': color_name,
                                                'wall_id': wall['id']
                                            })
                                            total_deleted_count += 1
                                
                                    if len(walls_to_delete) > 0:
                                        # 壁を削除
                                        updated_json = _delete_walls_in_json(updated_json, walls_to_delete)
                                    else:
                                        st.warning("⚠️ 削除対象の壁が見つかりません")
                        
                        elif edit_mode == "床を追加":
                            # ===== 床を追加モード =====
                            total_floor_count = 0
                            floor_details = []
                            
                            # JSONに floors キーがなければ初期化
                            if 'floors' not in updated_json:
                                updated_json['floors'] = []
                            
                            for rect_idx, (p1, p2) in enumerate(target_rects):
                                # 四角形範囲をメートル座標に変換
                                px_x1, px_y1 = p1
                                px_x2, px_y2 = p2
                                
                                # 画像座標からメートル座標に変換
                                def px_to_meter(px_x, px_y):
                                    # 画像座標からメートル座標への変換
                                    meter_x = min_x + (px_x - margin) / scale
                                    meter_y = min_y + (img_height - px_y - margin) / scale
                                    return meter_x, meter_y
                                
                                m_x1, m_y1 = px_to_meter(px_x1, px_y1)
                                m_x2, m_y2 = px_to_meter(px_x2, px_y2)
                                
                                # 座標を正規化（x1 < x2, y1 < y2）
                                floor_x1 = min(m_x1, m_x2)
                                floor_x2 = max(m_x1, m_x2)
                                floor_y1 = min(m_y1, m_y2)
                                floor_y2 = max(m_y1, m_y2)
                                
                                # 床データを追加
                                floor_data = {
                                    'x1': floor_x1,
                                    'y1': floor_y1,
                                    'x2': floor_x2,
                                    'y2': floor_y2
                                }
                                updated_json['floors'].append(floor_data)
                                total_floor_count += 1
                                
                                color_name = ["赤", "緑", "青", "黄", "マゼンタ", "シアン"][rect_idx % 6]
                                floor_details.append({
                                    'rect_idx': rect_idx,
                                    'color_name': color_name,
                                    'x1': floor_x1,
                                    'y1': floor_y1,
                                    'x2': floor_x2,
                                    'y2': floor_y2,
                                    'width': floor_x2 - floor_x1,
                                    'depth': floor_y2 - floor_y1
                                })
                            
                            if total_floor_count > 0:
                                st.success(f"✅ 合計 {total_floor_count} 個の床を追加しました")
                                
                                # 追加詳細を表示
                                st.markdown("**追加結果:**")
                                for detail in floor_details:
                                    st.write(
                                        f"#{detail['rect_idx']+1}（{detail['color_name']}）: "
                                        f"幅 {detail['width']:.2f}m × 奥行き {detail['depth']:.2f}m"
                                    )
                            else:
                                st.warning("⚠️ 床の追加に失敗しました")
                        
                        # 一時ファイルに保存
                        temp_json_path = Path(st.session_state.out_dir) / "walls_3d_edited.json"
                        with open(temp_json_path, 'w', encoding='utf-8') as f:
                            json.dump(updated_json, f, indent=2, ensure_ascii=False)
                        
                        # 再可視化（元の変換と同じスケールを使用）
                        # 窓追加モードの場合は追加した壁を赤色で表示
                        temp_viz_path = Path(st.session_state.out_dir) / "visualization_edited.png"
                        highlight_ids = added_wall_ids if edit_mode == "窓を追加" else None
                        visualize_3d_walls(str(temp_json_path), str(temp_viz_path), scale=int(viz_scale), highlight_wall_ids=highlight_ids, wall_color=(0, 0, 0), bg_color=(255, 255, 255))
                        
                        # 3Dビューア生成
                        temp_viewer_path = Path(st.session_state.out_dir) / "viewer_3d_edited.html"
                        _generate_3d_viewer_html(temp_json_path, temp_viewer_path)
                        
                        # セッション状態を更新（スケール校正で最新図を使用するため）
                        st.session_state.json_bytes = temp_json_path.read_bytes()
                        st.session_state.viz_bytes = temp_viz_path.read_bytes()
                        
                        # 編集後の画像を読み込み
                        edited_viz_bytes = temp_viz_path.read_bytes()
                        viewer_html_bytes = temp_viewer_path.read_bytes()
                        
                        # オブジェクト配置モード、階段を配置モード、線を結合モード、線を追加モードでは、比較表示をせず即座にセッションへ反映して続行する
                        if edit_mode in ("オブジェクトを配置", "階段を配置", "線を結合", "線を追加", "線を削除", "窓を追加"):
                            try:
                                # 更新済みJSON/可視化/ビューアは既に生成済みの場合がある
                                # ここでは最新の temp_* が存在すればそれをセッションへ反映する
                                st.session_state.json_bytes = temp_json_path.read_bytes()
                                st.session_state.json_name = temp_json_path.name
                                st.session_state.viz_bytes = temp_viz_path.read_bytes()
                                st.session_state.viewer_html_bytes = temp_viewer_path.read_bytes()
                                st.session_state.viewer_html_name = temp_viewer_path.name

                                # 状態を完全にクリアして続行（統一関数を使用）
                                _reset_selection_state()
                                
                                time.sleep(0.3)
                                st.rerun()
                            except Exception as e:
                                st.error(f"オブジェクト配置の保存中にエラー: {e}")
                                import traceback
                                st.code(traceback.format_exc())
                        else:
                            # 編集結果をセッション状態に保存（比較表示用）
                            if edit_mode == "線を結合":
                                edit_count = total_merged_count
                                edit_details = merge_details
                            elif edit_mode == "線を追加":
                                edit_count = total_added_count
                                edit_details = add_details
                            elif edit_mode == "床を追加":
                                edit_count = total_floor_count
                                edit_details = floor_details
                            else:  # 線を削除
                                edit_count = total_deleted_count
                                edit_details = delete_details

                            # デバッグログを保存
                            debug_log = st.session_state.get('debug_log', [])
                            
                            st.session_state.merge_result = {
                                'original_viz_bytes': original_viz_bytes,
                                'edited_viz_bytes': edited_viz_bytes,
                                'json_data': original_json_data,
                                'updated_json': updated_json,
                                'temp_json_path': temp_json_path,
                                'temp_viz_path': temp_viz_path,
                                'temp_viewer_path': temp_viewer_path,
                                'viewer_html_bytes': viewer_html_bytes,
                                'edit_count': edit_count,
                                'edit_details': edit_details,
                                'debug_log': debug_log.copy()  # デバッグログをコピーして保存
                            }
                            # 編集状態をリセット
                            st.session_state.rect_coords = []
                            st.session_state.rect_coords_list = []
                            # 窓追加パラメータもクリア
                            if 'window_execution_params' in st.session_state:
                                del st.session_state.window_execution_params
                            st.rerun()
                    
                    except Exception as e:
                        st.error(f"エラーが発生しました: {e}")
                        import traceback
                        st.code(traceback.format_exc())
            
            # 手動編集モードの最後：編集済みhtmlと照明付きhtmlのダウンロードボタン
            #st.divider()
            #st.subheader(" 編集済みファイルのダウンロード")
            
            
            # 編集済み3DビューアHTML（viewer_html_bytesを常に表示）
            if st.session_state.viewer_html_bytes:
                #st.download_button(
                #label=" 編集済み3Dモデルをダウンロード",
                #data=st.session_state.viewer_html_bytes,
                #type="primary",
                #file_name=st.session_state.viewer_html_name,
                #mime="text/html"
                #)
                
                # 編集済み3Dビューアを表示
                #st.subheader("🎨 編集済み3Dビューア")
                #import streamlit.components.v1 as components
                #components.html(
                #st.session_state.viewer_html_bytes.decode('utf-8'),
                #height=600,
                #scrolling=True
                #)
                pass
            else:
                # 可視化画像がない場合のエラーメッセージ
                st.warning("⚠️ 手動編集画面を表示するには、まずStep 1で図面を変換してください。")
                if st.button("📄 Step 1に戻る", type="primary"):
                    st.session_state.workflow_step = 1
                    st.rerun()

    # ============= 3Dビュー表示（Step3の下） =============
    with st.expander("🔭 3Dビュー", expanded=st.session_state.get('open_3d_expander', False)):
        if st.session_state.get('processed', False) and st.session_state.get('viz_bytes'):
            
            # 3Dビューア埋め込み表示
            if st.session_state.get('viewer_html_bytes'):
                st.markdown("### 🎨 3Dビューア")
                import streamlit.components.v1 as components
                components.html(
                    st.session_state.viewer_html_bytes.decode('utf-8'),
                    height=600,
                    scrolling=True
                )
                
                st.divider()
                
                # ダウンロードボタン
                st.download_button(
                    label="📥 3Dモデルをダウンロード",
                    data=st.session_state.viewer_html_bytes,
                    type="primary",
                    file_name=st.session_state.viewer_html_name,
                    mime="text/html",
                    #use_container_width=True
                )
        else:
            st.info("💡 Step 1で図面を変換すると、ここに3Dビューが表示されます。")
    
    # ============= フッター（全ステップ共通） =============
    st.divider()
    with st.expander("📋 利用規約", expanded=False):
        st.markdown("""
        ## 利用規約
        
        **最終更新日：2026年2月1日**
        
        本利用規約（以下「本規約」といいます）は、ichijo-3dmaker（以下「本サービス」といいます）の利用条件を定めるものです。  
        本サービスを利用するすべての方（以下「ユーザー」といいます）は、本規約に同意したものとみなされます。
        
        ---
        
        ### 第1条（本サービスの位置づけ）
        
        1. 本サービスは、2D図面等をもとに簡易的な3Dイメージを生成・表示することを目的とした、個人または小規模開発者による非公式サービスです。
        2. 本サービスは、株式会社一条工務店およびその関連会社が公式に提供・運営・監修するものではありません。
        3. 本サービスは、検証・試験運用を目的としたベータ版として提供される場合があります。
        
        ---
        
        ### 第2条（利用条件）
        
        1. ユーザーは、自己の責任において本サービスを利用するものとします。
        2. 本サービスの利用にあたり、特別な利用登録を必要としない場合があります。
        3. 本サービスの利用に必要な機器、通信環境および通信費用等は、すべてユーザーの負担とします。
        
        ---
        
        ### 第3条（本サービスの内容）
        
        1. 本サービスは、アップロードされたデータをもとに、簡易的な3D表現や可視化結果を提供します。
        2. 本サービスで生成される3Dイメージ、数値、判定結果等は、あくまで参考情報であり、設計・施工・契約等を保証するものではありません。
        3. 本サービスの一部機能は、利用登録を行ったユーザーにのみ提供される場合があります。
        4. 提供される機能の内容、仕様、表示方法等は、予告なく変更または停止されることがあります。
        
        ---
        
        ### 第4条（禁止事項）
        
        ユーザーは、本サービスの利用にあたり、以下の行為を行ってはなりません。
        
        1. 法令または公序良俗に違反する行為
        2. 本サービスの運営を妨害する行為
        3. 本サービスの不具合や仕様を悪用する行為
        4. 第三者または運営者の権利・利益を侵害する行為
        5. その他、運営者が不適切と判断する行為
        
        ---
        
        ### 第5条（知的財産権）
        
        1. 本サービスに関するプログラム、UI、文章、ロゴ等の著作権および知的財産権は、運営者または正当な権利者に帰属します。
        2. ユーザーは、本サービスの内容を、私的利用の範囲を超えて無断で複製・転載・配布してはなりません。
        
        ---
        
        ### 第6条（免責事項）
        
        1. 本サービスは、正確性・完全性・有用性を保証するものではありません。
        2. 本サービスの利用または利用不能により生じた損害について、運営者は一切の責任を負いません。
        3. 本サービスの内容は、予告なく変更、中断、終了されることがあります。
        4. 本サービスを利用したことによる設計判断、施工判断、金銭的判断について、運営者は責任を負いません。
        
        ---
        
        ### 第7条（サービスの停止・終了）
        
        運営者は、以下の場合、ユーザーへの事前通知なく本サービスの全部または一部を停止または終了することがあります。
        
        1. システム保守または障害対応が必要な場合
        2. 本サービスの継続が困難と判断された場合
        3. その他、運営者が必要と判断した場合
        
        ---
        
        ### 第8条（規約の変更）
        
        1. 運営者は、必要に応じて本規約を変更することができます。
        2. 変更後の規約は、本サービス上に表示された時点で効力を生じるものとします。
        
        ---
        
        ### 第9条（準拠法・管轄）
        
        本規約は日本法を準拠法とし、本サービスに関して生じた紛争については、日本国内の裁判所を専属的合意管轄とします。
        """)
    
    # フッター情報
    try:
        import ichijo_core
        version_info = f"v{ichijo_core.__version__}"
    except:
        version_info = ""
    
    st.markdown(
        f"""
        <div style='text-align: center; color: #888; padding: 20px; margin-top: 20px; border-top: 1px solid #ddd;'>
            <p style='margin: 5px 0; font-size: 0.9em;'>© 2026 Ichijo 3D Maker {version_info}</p>
            <p style='margin: 5px 0; font-size: 0.9em;'>※ 本サービスは一条工務店の公式アプリではありません</p>
            <p style='margin: 5px 0; font-size: 0.8em;'>本サービスのご利用には、上記の利用規約への同意が必要です。</p>
        </div>
        """,
        unsafe_allow_html=True
    )



if __name__ == "__main__":
    main()

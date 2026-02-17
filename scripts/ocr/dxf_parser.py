"""
DXF Parser — ezdxf 기반 DXF/DWG 파일 직접 파싱

OCR 없이 CAD 파일의 구조 정보를 직접 추출:
- 레이어 구조 분석
- 치수 (DIMENSION) 엔티티 추출
- 텍스트 엔티티 (TEXT, MTEXT) 추출
- 블록 참조 (INSERT) 분석
- 구조 요소 레이어별 분류
"""

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Any

log = logging.getLogger(__name__)

try:
    import ezdxf
    EZDXF_AVAILABLE = True
except ImportError:
    EZDXF_AVAILABLE = False
    log.warning("ezdxf 미설치: DXF 파싱 불가")


@dataclass
class DxfAnalysis:
    """DXF 파일 분석 결과."""
    file_name: str = ""
    layers: List[Dict[str, Any]] = field(default_factory=list)
    dimensions: List[Dict[str, Any]] = field(default_factory=list)
    texts: List[Dict[str, Any]] = field(default_factory=list)
    blocks: List[Dict[str, Any]] = field(default_factory=list)
    drawing_extent: Dict[str, float] = field(default_factory=dict)
    entity_count: Dict[str, int] = field(default_factory=dict)
    structural_elements: List[Dict[str, Any]] = field(default_factory=list)
    total_entities: int = 0
    dxf_version: str = ""
    units: str = ""


# ── 구조 요소 레이어 패턴 매핑 ──────────────────────────────
STRUCTURAL_LAYER_PATTERNS = {
    "column": re.compile(r"(?:col|column|기둥|psrc)", re.IGNORECASE),
    "beam": re.compile(r"(?:beam|보|girder|거더|hmb)", re.IGNORECASE),
    "slab": re.compile(r"(?:slab|슬래브|deck|바닥)", re.IGNORECASE),
    "wall": re.compile(r"(?:wall|벽|shear)", re.IGNORECASE),
    "footing": re.compile(r"(?:foot|기초|found|pile)", re.IGNORECASE),
    "rebar": re.compile(r"(?:rebar|철근|reinf|bar|배근)", re.IGNORECASE),
    "anchor": re.compile(r"(?:anchor|앙카|앵커|bolt)", re.IGNORECASE),
    "embed": re.compile(r"(?:embed|임베드|plate|ep[-_])", re.IGNORECASE),
    "dimension": re.compile(r"(?:dim|치수|annotation)", re.IGNORECASE),
    "grid": re.compile(r"(?:grid|축|axis|center)", re.IGNORECASE),
    "text": re.compile(r"(?:text|문자|anno|note)", re.IGNORECASE),
}


class DxfParser:
    """DXF/DWG 파일 직접 파싱.

    Usage:
        parser = DxfParser()
        analysis = parser.parse("drawing.dxf")
        summary = parser.summarize(analysis)
    """

    def __init__(self):
        if not EZDXF_AVAILABLE:
            raise RuntimeError("ezdxf 라이브러리가 설치되어 있지 않습니다.")

    def parse(self, file_path: str) -> DxfAnalysis:
        """DXF 파일 분석.

        Args:
            file_path: DXF 파일 경로

        Returns:
            DxfAnalysis 분석 결과
        """
        path = Path(file_path)
        analysis = DxfAnalysis(file_name=path.name)

        try:
            doc = ezdxf.readfile(str(path))
        except Exception as e:
            log.error("DXF 파일 읽기 실패: %s - %s", file_path, e)
            return analysis

        analysis.dxf_version = doc.dxfversion

        # 단위 정보
        try:
            header = doc.header
            units_val = header.get("$INSUNITS", 0)
            units_map = {
                0: "Unitless", 1: "Inches", 2: "Feet", 3: "Miles",
                4: "Millimeters", 5: "Centimeters", 6: "Meters",
            }
            analysis.units = units_map.get(units_val, f"Code_{units_val}")
        except Exception:
            analysis.units = "Unknown"

        # 레이어 분석
        analysis.layers = self._extract_layers(doc)

        # ModelSpace 엔티티 분석
        msp = doc.modelspace()
        entity_counter: Counter = Counter()

        for entity in msp:
            entity_counter[entity.dxftype()] += 1

        analysis.entity_count = dict(entity_counter)
        analysis.total_entities = sum(entity_counter.values())

        # 세부 추출
        analysis.dimensions = self._extract_dimensions(msp)
        analysis.texts = self._extract_texts(msp)
        analysis.blocks = self._extract_blocks(msp)
        analysis.drawing_extent = self._extract_extent(msp)
        analysis.structural_elements = self._classify_structural_elements(doc)

        log.info(
            "DXF 분석 완료: %s - 레이어 %d개, 엔티티 %d개, 치수 %d개",
            path.name, len(analysis.layers), analysis.total_entities,
            len(analysis.dimensions),
        )

        return analysis

    def _extract_layers(self, doc) -> List[Dict[str, Any]]:
        """레이어 목록 + 엔티티 수."""
        layers = []
        msp = doc.modelspace()

        # 레이어별 엔티티 수 집계
        layer_counts: Counter = Counter()
        for entity in msp:
            layer_counts[entity.dxf.layer] += 1

        for layer in doc.layers:
            name = layer.dxf.name
            layers.append({
                "name": name,
                "color": layer.color,
                "is_on": layer.is_on(),
                "is_frozen": layer.is_frozen(),
                "entity_count": layer_counts.get(name, 0),
                "structural_type": self._classify_layer(name),
            })

        # 엔티티 수 기준 내림차순 정렬
        layers.sort(key=lambda x: x["entity_count"], reverse=True)
        return layers

    def _extract_dimensions(self, msp) -> List[Dict[str, Any]]:
        """DIMENSION 엔티티에서 치수 추출."""
        dimensions = []

        for entity in msp.query("DIMENSION"):
            try:
                dim_info: Dict[str, Any] = {
                    "layer": entity.dxf.layer,
                    "type": entity.dxftype(),
                }

                # 치수 타입별 처리
                dim_type = entity.dxf.get("dimtype", 0)
                if dim_type == 0:
                    dim_info["dim_type"] = "linear"
                elif dim_type == 1:
                    dim_info["dim_type"] = "aligned"
                elif dim_type == 2:
                    dim_info["dim_type"] = "angular"
                elif dim_type == 3:
                    dim_info["dim_type"] = "diameter"
                elif dim_type == 4:
                    dim_info["dim_type"] = "radius"
                else:
                    dim_info["dim_type"] = f"type_{dim_type}"

                # 텍스트 오버라이드
                text_override = entity.dxf.get("text", "")
                if text_override:
                    dim_info["text"] = text_override

                # 실측값 (measurement)
                try:
                    dim_info["measurement"] = entity.dxf.get("actual_measurement", None)
                except Exception:
                    pass

                # 위치 정보
                try:
                    defpoint = entity.dxf.get("defpoint", None)
                    if defpoint:
                        dim_info["position"] = {
                            "x": round(defpoint.x, 2),
                            "y": round(defpoint.y, 2),
                        }
                except Exception:
                    pass

                dimensions.append(dim_info)

            except Exception as e:
                log.debug("치수 추출 오류: %s", e)

        return dimensions

    def _extract_texts(self, msp, limit: int = 200) -> List[Dict[str, Any]]:
        """TEXT, MTEXT 엔티티에서 텍스트 추출."""
        texts = []

        for entity in msp.query("TEXT MTEXT"):
            if len(texts) >= limit:
                break

            try:
                if entity.dxftype() == "TEXT":
                    content = entity.dxf.text
                    insert = entity.dxf.insert
                elif entity.dxftype() == "MTEXT":
                    content = entity.plain_text()
                    insert = entity.dxf.insert
                else:
                    continue

                if not content or not content.strip():
                    continue

                texts.append({
                    "content": content.strip(),
                    "layer": entity.dxf.layer,
                    "position": {
                        "x": round(insert.x, 2),
                        "y": round(insert.y, 2),
                    },
                    "type": entity.dxftype(),
                })

            except Exception as e:
                log.debug("텍스트 추출 오류: %s", e)

        return texts

    def _extract_blocks(self, msp, limit: int = 100) -> List[Dict[str, Any]]:
        """INSERT (블록 참조) 추출."""
        blocks = []
        block_counter: Counter = Counter()

        for entity in msp.query("INSERT"):
            if len(blocks) >= limit:
                break

            try:
                name = entity.dxf.name
                block_counter[name] += 1

                # 동일 블록은 첫 번째만 상세 기록
                if block_counter[name] <= 3:
                    blocks.append({
                        "name": name,
                        "layer": entity.dxf.layer,
                        "insert_point": {
                            "x": round(entity.dxf.insert.x, 2),
                            "y": round(entity.dxf.insert.y, 2),
                        },
                        "scale": {
                            "x": round(entity.dxf.get("xscale", 1.0), 3),
                            "y": round(entity.dxf.get("yscale", 1.0), 3),
                        },
                        "rotation": round(entity.dxf.get("rotation", 0.0), 1),
                    })

            except Exception as e:
                log.debug("블록 추출 오류: %s", e)

        # 블록 빈도 추가
        for block in blocks:
            block["total_count"] = block_counter[block["name"]]

        return blocks

    def _extract_extent(self, msp) -> Dict[str, float]:
        """도면 범위 (bounding box)."""
        try:
            from ezdxf import bbox as ezdxf_bbox
            cache = ezdxf_bbox.Cache()
            box = ezdxf_bbox.extents(msp, cache=cache)
            if box.has_data:
                return {
                    "min_x": round(box.extmin.x, 2),
                    "min_y": round(box.extmin.y, 2),
                    "max_x": round(box.extmax.x, 2),
                    "max_y": round(box.extmax.y, 2),
                    "width": round(box.extmax.x - box.extmin.x, 2),
                    "height": round(box.extmax.y - box.extmin.y, 2),
                }
        except Exception as e:
            log.debug("도면 범위 추출 실패: %s", e)

        return {}

    def _classify_layer(self, layer_name: str) -> str:
        """레이어명으로 구조 요소 타입 분류."""
        for stype, pattern in STRUCTURAL_LAYER_PATTERNS.items():
            if pattern.search(layer_name):
                return stype
        return "other"

    def _classify_structural_elements(self, doc) -> List[Dict[str, Any]]:
        """레이어별 구조 요소 분류 요약."""
        msp = doc.modelspace()
        type_layers: Dict[str, List[str]] = {}

        for layer in doc.layers:
            stype = self._classify_layer(layer.dxf.name)
            if stype != "other":
                type_layers.setdefault(stype, []).append(layer.dxf.name)

        elements = []
        for stype, layer_names in sorted(type_layers.items()):
            total_entities = 0
            for name in layer_names:
                total_entities += sum(
                    1 for e in msp if e.dxf.layer == name
                )

            elements.append({
                "type": stype,
                "layers": layer_names,
                "entity_count": total_entities,
            })

        return elements

    def summarize(self, analysis: DxfAnalysis) -> str:
        """분석 결과 텍스트 요약.

        텔레그램 메시지용 구조화된 요약.
        """
        lines = [
            f"📐 DXF 도면 분석: {analysis.file_name}",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
        ]

        # 기본 정보
        lines.append(f"📋 DXF 버전: {analysis.dxf_version}")
        lines.append(f"📏 단위: {analysis.units}")
        lines.append(f"📊 총 엔티티: {analysis.total_entities:,}개")

        # 도면 범위
        if analysis.drawing_extent:
            ext = analysis.drawing_extent
            lines.append(
                f"📐 도면 범위: {ext.get('width', 0):.0f} x {ext.get('height', 0):.0f} "
                f"({analysis.units})"
            )

        # 엔티티 타입별
        if analysis.entity_count:
            lines.append(f"\n🔧 엔티티 타입별 수량:")
            for etype, count in sorted(
                analysis.entity_count.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:10]:
                lines.append(f"  • {etype}: {count:,}개")

        # 레이어 분석
        if analysis.layers:
            active_layers = [l for l in analysis.layers if l["entity_count"] > 0]
            lines.append(f"\n📂 레이어: {len(analysis.layers)}개 (활성: {len(active_layers)}개)")
            for layer in active_layers[:15]:
                stype = layer["structural_type"]
                type_badge = f" [{stype}]" if stype != "other" else ""
                lines.append(
                    f"  • {layer['name']}{type_badge}: {layer['entity_count']:,}개"
                )

        # 구조 요소 분류
        if analysis.structural_elements:
            lines.append(f"\n🏗️ 구조 요소 분류:")
            type_names = {
                "column": "기둥", "beam": "보", "slab": "슬래브",
                "wall": "벽", "footing": "기초", "rebar": "철근",
                "anchor": "앵커", "embed": "임베드", "grid": "그리드",
            }
            for elem in analysis.structural_elements:
                name = type_names.get(elem["type"], elem["type"])
                lines.append(
                    f"  • {name}: {elem['entity_count']:,}개 "
                    f"(레이어: {', '.join(elem['layers'][:3])})"
                )

        # 치수 정보
        if analysis.dimensions:
            lines.append(f"\n📏 치수: {len(analysis.dimensions)}개")
            dim_types: Counter = Counter()
            for dim in analysis.dimensions:
                dim_types[dim.get("dim_type", "unknown")] += 1
            for dtype, count in dim_types.most_common():
                lines.append(f"  • {dtype}: {count}개")

            # 텍스트가 있는 치수 샘플
            text_dims = [d for d in analysis.dimensions if d.get("text")]
            if text_dims:
                lines.append("  주요 치수:")
                for dim in text_dims[:10]:
                    lines.append(f"    - {dim['text']}")

        # 텍스트 엔티티
        if analysis.texts:
            lines.append(f"\n📝 텍스트: {len(analysis.texts)}개")
            # P5 관련 텍스트 하이라이트
            p5_texts = [
                t for t in analysis.texts
                if any(kw in t["content"].upper()
                       for kw in ["SEN", "EP-", "PSRC", "HMB", "SHOP", "PLEG", "FCC"])
            ]
            if p5_texts:
                lines.append("  P5 관련 텍스트:")
                for t in p5_texts[:15]:
                    lines.append(f"    • [{t['layer']}] {t['content'][:60]}")

        # 블록
        if analysis.blocks:
            unique_blocks = set(b["name"] for b in analysis.blocks)
            lines.append(f"\n📦 블록 참조: {len(unique_blocks)}종")
            for block in analysis.blocks[:10]:
                lines.append(
                    f"  • {block['name']} (x{block['total_count']}) "
                    f"[{block['layer']}]"
                )

        return "\n".join(lines)

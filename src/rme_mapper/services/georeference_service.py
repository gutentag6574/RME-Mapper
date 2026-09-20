"""Сервис ручной геопривязки изображений по контрольным точкам (GeoreferenceService).

Реализует:
1. Безопасную инспекцию форматов и размеров изображений (защита от Decompression Bomb, чтение EXIF-ориентации).
2. Математический солвер 2D аффинного преобразования (точный метод для 3 точек, МНК для >3 точек).
3. Валидацию коллинеарности, дубликатов, вырожденных матриц, NaN/Inf.
4. Расчет остаточных невязок и RMSE в физических единицах (метрах).
5. Экспорт World File (.pgw, .jgw, .tfw, .prj) без изменения исходного файла.
"""

import logging
import math
from pathlib import Path
from typing import Any
import numpy as np
from PIL import Image, ImageOps
import pyproj
from PySide6.QtGui import QImage, QPixmap

from rme_mapper.models.georeference import ControlPoint

logger = logging.getLogger("rme_mapper.services.georeference")

# Защита от Decompression Bomb (максимум 250 мегапикселей для геоинформационных растров)
MAX_SAFE_PIXELS = 250_000_000
Image.MAX_IMAGE_PIXELS = MAX_SAFE_PIXELS

SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


class GeoreferenceService:
    """Сервис математических и графических операций для геопривязки растровых изображений."""

    @staticmethod
    def inspect_image(path: Path | str) -> dict[str, Any]:
        """Инспекция метаданных растрового изображения без полной загрузки в память."""
        p = Path(path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Файл изображения не найден: {p}")

        ext = p.suffix.lower()
        if ext not in SUPPORTED_IMAGE_EXTENSIONS:
            raise ValueError(
                f"Неподдерживаемый формат изображения '{ext}'. Поддерживаются: {', '.join(sorted(SUPPORTED_IMAGE_EXTENSIONS))}"
            )

        file_size = p.stat().st_size
        if file_size == 0:
            raise ValueError("Файл изображения имеет нулевой размер (0 байт).")

        try:
            with Image.open(p) as img:
                raw_w, raw_h = img.size
                fmt = img.format or ext.lstrip(".").upper()
                mode = img.mode

                # Проверка ограничения Decompression Bomb
                num_pixels = raw_w * raw_h
                if num_pixels > MAX_SAFE_PIXELS:
                    raise ValueError(
                        f"Разрешение изображения ({raw_w} × {raw_h} = {num_pixels / 1e6:.1f} Мпкс) "
                        f"превышает предел безопасности ({MAX_SAFE_PIXELS / 1e6:.1f} Мпкс)."
                    )

                # Проверка ориентации EXIF
                transposed = ImageOps.exif_transpose(img)
                w, h = transposed.size if transposed else (raw_w, raw_h)

                has_alpha = "A" in mode or mode == "RGBA"

                return {
                    "path": str(p),
                    "filename": p.name,
                    "width": int(w),
                    "height": int(h),
                    "raw_width": int(raw_w),
                    "raw_height": int(raw_h),
                    "format": str(fmt),
                    "mode": str(mode),
                    "has_alpha": bool(has_alpha),
                    "file_size": file_size,
                }
        except Exception as e:
            logger.warning("Ошибка инспекции файла изображения %s: %s", p, e)
            raise ValueError(f"Не удалось открыть файл изображения: {e}") from e

    @staticmethod
    def load_preview_image(path: Path | str, max_dimension: int = 2048) -> tuple[QImage, tuple[int, int]]:
        """Безопасная загрузка уменьшенного превью изображения без перегрузки оперативной памяти.

        Возвращает:
            tuple[QImage, (full_width, full_height)]
        """
        p = Path(path).resolve()
        info = GeoreferenceService.inspect_image(p)
        full_w, full_h = info["width"], info["height"]

        with Image.open(p) as img:
            transposed = ImageOps.exif_transpose(img)
            active_img = transposed if transposed is not None else img

            max_dim = max(full_w, full_h)
            if max_dim > max_dimension:
                scale = max_dimension / max_dim
                preview_w = max(1, int(round(full_w * scale)))
                preview_h = max(1, int(round(full_h * scale)))
                resampled = active_img.resize((preview_w, preview_h), Image.Resampling.BILINEAR)
            else:
                resampled = active_img

            # Конвертация в RGBA
            if resampled.mode != "RGBA":
                resampled = resampled.convert("RGBA")

            data = resampled.tobytes("raw", "RGBA")
            qimg = QImage(data, resampled.width, resampled.height, resampled.width * 4, QImage.Format.Format_RGBA8888)
            return qimg.copy(), (full_w, full_h)

    @staticmethod
    def load_full_image(path: Path | str) -> tuple[QImage, tuple[int, int]]:
        """Загрузка изображения в полном разрешении для отображения на холсте и экспорта."""
        p = Path(path).resolve()
        info = GeoreferenceService.inspect_image(p)
        full_w, full_h = info["width"], info["height"]

        with Image.open(p) as img:
            transposed = ImageOps.exif_transpose(img)
            active_img = transposed if transposed is not None else img
            if active_img.mode != "RGBA":
                active_img = active_img.convert("RGBA")

            data = active_img.tobytes("raw", "RGBA")
            qimg = QImage(data, active_img.width, active_img.height, active_img.width * 4, QImage.Format.Format_RGBA8888)
            return qimg.copy(), (full_w, full_h)

    @staticmethod
    def solve_affine(
        control_points: list[ControlPoint],
        crs_str: str = "EPSG:4326",
        crs: str | None = None,
    ) -> tuple[tuple[float, float, float, float, float, float], list[ControlPoint], float]:
        if crs is not None:
            crs_str = crs
        """Расчет 2D аффинной трансформации по контрольным точкам.

        Математическая модель:
            target_X = a * pixel_x + b * pixel_y + c
            target_Y = d * pixel_x + e * pixel_y + f

        Где:
            pixel_x, pixel_y — непрерывные координаты пикселей (origin: top-left corner).
            target_X, target_Y — целевые координаты в CRS (always_xy=True).

        Возвращает:
            tuple[affine_coeffs, updated_control_points, rmse_meters]
            где affine_coeffs = (a, b, c, d, e, f)
        """
        from rme_mapper.models.georeference import MAX_CONTROL_POINTS
        if len(control_points) > MAX_CONTROL_POINTS:
            raise ValueError(f"Превышен лимит контрольных точек: максимум {MAX_CONTROL_POINTS}")

        enabled_pts = [p for p in control_points if p.enabled]
        if len(enabled_pts) < 3:
            raise ValueError("Недостаточно контрольных точек: требуется как минимум 3 активные точки.")

        # 1. Извлечение координат
        px = np.array([float(p.pixel_x) for p in enabled_pts], dtype=np.float64)
        py = np.array([float(p.pixel_y) for p in enabled_pts], dtype=np.float64)
        tx = np.array([float(p.target_x) for p in enabled_pts], dtype=np.float64)
        ty = np.array([float(p.target_y) for p in enabled_pts], dtype=np.float64)

        # 2. Проверка на NaN / Inf
        if (
            np.any(np.isnan(px))
            or np.any(np.isnan(py))
            or np.any(np.isnan(tx))
            or np.any(np.isnan(ty))
            or np.any(np.isinf(px))
            or np.any(np.isinf(py))
            or np.any(np.isinf(tx))
            or np.any(np.isinf(ty))
        ):
            raise ValueError("Координаты контрольных точек содержат недопустимые значения (NaN или Inf).")

        # 3. Проверка на дублирование пиксельных координат
        n = len(enabled_pts)
        for i in range(n):
            for j in range(i + 1, n):
                if abs(px[i] - px[j]) < 1e-6 and abs(py[i] - py[j]) < 1e-6:
                    raise ValueError(
                        f"Контрольные точки {enabled_pts[i].name or i+1} и {enabled_pts[j].name or j+1} имеют одинаковые координаты на изображении."
                    )
                if abs(tx[i] - tx[j]) < 1e-9 and abs(ty[i] - ty[j]) < 1e-9:
                    raise ValueError(
                        f"Контрольные точки {enabled_pts[i].name or i+1} и {enabled_pts[j].name or j+1} имеют одинаковые целевые координаты."
                    )

        # 4. Построение матрицы плана (Design Matrix) M: N x 3
        # [pixel_x, pixel_y, 1]
        ones = np.ones(n, dtype=np.float64)
        M = np.column_stack([px, py, ones])

        # 5. Проверка коллинеарности пиксельных точек
        # Ранг матрицы должен быть равен 3
        rank = np.linalg.matrix_rank(M, tol=1e-7)
        if rank < 3:
            raise ValueError(
                "Контрольные точки расположены на одной прямой (коллинеарны). Разместите точки по площади изображения."
            )

        # 6. Решение системы уравнений
        if n == 3:
            det = np.linalg.det(M)
            if abs(det) < 1e-10:
                raise ValueError("Матрица контрольных точек вырождена (коллинеарность или близкие точки).")
            coeffs_x = np.linalg.solve(M, tx)
            coeffs_y = np.linalg.solve(M, ty)
        else:
            # МНК (Linear Least Squares) через SVD
            coeffs_x, _, _, _ = np.linalg.lstsq(M, tx, rcond=None)
            coeffs_y, _, _, _ = np.linalg.lstsq(M, ty, rcond=None)

        a, b, c = float(coeffs_x[0]), float(coeffs_x[1]), float(coeffs_x[2])
        d, e, f = float(coeffs_y[0]), float(coeffs_y[1]), float(coeffs_y[2])

        # 7. Проверка вырожденности полученного аффинного преобразования
        det_affine = a * e - b * d
        if abs(det_affine) < 1e-15 or np.isnan(det_affine) or np.isinf(det_affine):
            raise ValueError("Вычисленная трансформация вырождена (целевые координаты точек коллинеарны).")

        # 8. Определение типа CRS (географическая или спроецированная) для расчета невязок в метрах
        is_geographic = False
        geod = None
        unit_to_meter = 1.0
        try:
            parsed_crs = pyproj.CRS.from_user_input(crs_str)
        except Exception as e:
            raise ValueError(f"Недопустимая или неподдерживаемая CRS: '{crs_str}'") from e

        is_geographic = parsed_crs.is_geographic
        if is_geographic:
            try:
                geod = parsed_crs.get_geod()
            except Exception:
                geod = pyproj.Geod(ellps="WGS84")
        else:
            if parsed_crs.axis_info:
                factor = getattr(parsed_crs.axis_info[0], "unit_conversion_factor", None)
                if factor is not None and factor > 0:
                    unit_to_meter = float(factor)

        # 9. Расчет невязок (Residuals) для каждой точки
        total_sq_err = 0.0
        for pt in control_points:
            if not pt.enabled:
                pt.residual_x = None
                pt.residual_y = None
                pt.residual_total = None
                continue

            pred_x = a * pt.pixel_x + b * pt.pixel_y + c
            pred_y = d * pt.pixel_x + e * pt.pixel_y + f

            res_x = float(pred_x - pt.target_x)
            res_y = float(pred_y - pt.target_y)

            pt.residual_x = res_x
            pt.residual_y = res_y

            if is_geographic and geod is not None:
                # Геодезическое расстояние в метрах между целевой точкой и спрогнозированной
                try:
                    _, _, dist_m = geod.inv(pt.target_x, pt.target_y, pred_x, pred_y)
                    pt.residual_total = float(dist_m)
                except Exception:
                    # Резервный расчет через экваториальный градус (~111.32 км)
                    pt.residual_total = float(math.hypot(res_x, res_y) * 111_320.0)
            else:
                # В спроецированной CRS переводим единицы координат в метры (например, US Survey Foot)
                pt.residual_total = float(math.hypot(res_x, res_y) * unit_to_meter)

            if pt.enabled:
                total_sq_err += (pt.residual_total ** 2)

        # 10. Расчет общего RMSE в метрах
        rmse = float(math.sqrt(total_sq_err / n)) if n > 0 else 0.0

        affine_tuple = (a, b, c, d, e, f)
        return affine_tuple, control_points, rmse

    @staticmethod
    def export_world_file(
        image_path: Path | str,
        affine_coeffs: tuple[float, float, float, float, float, float],
        crs_str: str | None = None,
        target_dir: Path | str | None = None,
        crs: str | None = None,
    ) -> list[Path]:
        if crs is not None:
            crs_str = crs
        """Экспорт коэффициентов аффинной трансформации в файл привязки World File и файл проекции .prj.

        Формат World File (6 строк):
        Line 1: a (размер пикселя по X)
        Line 2: d (вращение по Y)
        Line 3: b (вращение по X)
        Line 4: e (размер пикселя по Y, обычно отрицательный)
        Line 5: c + a/2 + b/2 (координата центра верхнего левого пикселя по X)
        Line 6: f + d/2 + e/2 (координата центра верхнего левого пикселя по Y)

        Расширения World File:
        .png  -> .pgw
        .jpg  -> .jgw
        .jpeg -> .jgw
        .tif  -> .tfw
        .tiff -> .tfw
        """
        p = Path(image_path).resolve()
        out_dir = Path(target_dir).resolve() if target_dir is not None else p.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        ext = p.suffix.lower()
        if ext == ".png":
            wf_ext = ".pgw"
        elif ext in (".jpg", ".jpeg"):
            wf_ext = ".jgw"
        elif ext in (".tif", ".tiff"):
            wf_ext = ".tfw"
        else:
            wf_ext = ".wld"

        wf_path = out_dir / f"{p.stem}{wf_ext}"
        a, b, c, d, e, f = affine_coeffs

        # В world file координаты центра пикселя (0.5, 0.5):
        center_x = c + 0.5 * a + 0.5 * b
        center_y = f + 0.5 * d + 0.5 * e

        lines = [
            f"{a:.12f}",
            f"{d:.12f}",
            f"{b:.12f}",
            f"{e:.12f}",
            f"{center_x:.12f}",
            f"{center_y:.12f}",
        ]

        with open(wf_path, "w", encoding="utf-8") as wf:
            wf.write("\n".join(lines) + "\n")

        exported_files = [wf_path]

        # Экспорт PRJ, если задан CRS
        if crs_str:
            try:
                crs_obj = pyproj.CRS.from_user_input(crs_str)
                wkt = crs_obj.to_wkt()
                prj_path = out_dir / f"{p.stem}.prj"
                with open(prj_path, "w", encoding="utf-8") as pf:
                    pf.write(wkt)
                exported_files.append(prj_path)
            except Exception as crs_err:
                logger.warning("Не удалось сформировать WKT для .prj файла: %s", crs_err)

        return exported_files

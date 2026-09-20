"""Современная реализация растрового бэкенда ModernGeoTiffBackend на базе rasterio."""

import logging
import math
from pathlib import Path
from typing import Any
import numpy as np

from rme_mapper.backends.raster_backend import RasterDataBackend

logger = logging.getLogger("rme_mapper.backends.raster")

try:
    import rasterio
    from rasterio.enums import ColorInterp, Resampling
    from rasterio.windows import Window, from_bounds
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False


class ModernGeoTiffBackend(RasterDataBackend):
    """Современный бэкенд доступа к геопривязанным растрам GeoTIFF (*.tif, *.tiff).

    Использует rasterio в строгом режиме чтения ('r').
    Никогда не модифицирует исходный файл, не создает sidecar-файлы (.ovr, .aux.xml).
    """

    MAX_CACHE_ENTRIES = 4

    def __init__(self) -> None:
        if not HAS_RASTERIO:
            logger.warning("Библиотека rasterio не установлена. ModernGeoTiffBackend недоступен.")
        self._cache: dict[str, tuple[np.ndarray, dict[str, Any]]] = {}
        self._open_datasets: dict[str, Any] = {}

    @classmethod
    def is_available(cls) -> bool:
        """Проверка доступности rasterio в текущей среде."""
        return HAS_RASTERIO

    def _get_dataset(self, path: Path | str) -> Any:
        """Безопасное открытие файла в режиме строгого чтения ('r')."""
        if not HAS_RASTERIO:
            raise RuntimeError("Библиотека rasterio не установлена. Поддержка GeoTIFF недоступна.")

        p = Path(path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Файл растра не найден: {p}")

        key = str(p)
        if key in self._open_datasets:
            ds = self._open_datasets[key]
            if not ds.closed:
                return ds

        try:
            ds = rasterio.open(str(p), mode="r")
            self._open_datasets[key] = ds
            return ds
        except Exception as e:
            logger.exception("Ошибка открытия GeoTIFF %s: %s", p, e)
            raise

    def inspect_raster(self, path: Path | str) -> dict[str, Any]:
        """Инспекция метаданных растра."""
        ds = self._get_dataset(path)

        crs_str: str | None = None
        if ds.crs:
            crs_str = ds.crs.to_string() if hasattr(ds.crs, "to_string") else str(ds.crs)

        bounds = (
            float(ds.bounds.left),
            float(ds.bounds.bottom),
            float(ds.bounds.right),
            float(ds.bounds.top),
        )
        extent = {
            "xmin": bounds[0],
            "ymin": bounds[1],
            "xmax": bounds[2],
            "ymax": bounds[3],
        }

        # Аффинная матрица
        t = ds.transform
        affine_tuple = (float(t.a), float(t.b), float(t.c), float(t.d), float(t.e), float(t.f))

        # Проверка валидности геопривязки
        # Растр считается негеопривязанным, если нет CRS или трансформация вырождена
        det = t.a * t.e - t.b * t.d
        is_valid_georef = (crs_str is not None) and (abs(det) > 1e-12)

        # Анализ каналов и alpha
        has_alpha = False
        if hasattr(ds, "colorinterp") and ds.colorinterp:
            for ci in ds.colorinterp:
                if ci == ColorInterp.alpha:
                    has_alpha = True
                    break
        elif ds.count == 4:
            has_alpha = False  # Без явной метаданной не считаем 4-й канал alpha автоматически

        # Проверка маски
        has_mask = False
        try:
            if hasattr(ds, "mask_flag_enums") and ds.mask_flag_enums:
                has_mask = any(len(flags) > 0 for flags in ds.mask_flag_enums)
        except Exception:
            pass

        # Доступные overviews первого канала
        overviews: list[int] = []
        try:
            overviews = list(ds.overviews(1))
        except Exception:
            pass

        dtype_str = str(ds.dtypes[0]) if ds.dtypes else "unknown"

        return {
            "width": int(ds.width),
            "height": int(ds.height),
            "count": int(ds.count),
            "band_count": int(ds.count),
            "crs": crs_str,
            "bounds": bounds,
            "extent": extent,
            "transform": affine_tuple,
            "dtype": dtype_str,
            "nodata": ds.nodata,
            "has_alpha": has_alpha,
            "has_mask": has_mask,
            "overviews": overviews,
            "is_valid_georef": is_valid_georef,
        }

    def get_crs(self, path: Path | str) -> str | None:
        """Получение CRS растра."""
        try:
            info = self.inspect_raster(path)
            return info.get("crs")
        except Exception:
            return None

    def get_extent(self, path: Path | str) -> dict[str, float] | None:
        """Получение охвата растра."""
        try:
            info = self.inspect_raster(path)
            return info.get("extent")
        except Exception:
            return None

    def get_size(self, path: Path | str) -> tuple[int, int] | None:
        """Получение размеров растра."""
        try:
            info = self.inspect_raster(path)
            return (info["width"], info["height"])
        except Exception:
            return None

    def get_band_count(self, path: Path | str) -> int:
        """Получение количества каналов."""
        try:
            info = self.inspect_raster(path)
            return info.get("band_count", 0)
        except Exception:
            return 0

    def get_nodata(self, path: Path | str) -> float | None:
        """Получение значения NoData."""
        try:
            info = self.inspect_raster(path)
            return info.get("nodata")
        except Exception:
            return None

    @staticmethod
    def _normalize_to_rgba(
        data: np.ndarray,
        colorinterp: list[Any] | None,
        nodata: float | None,
        mask: np.ndarray | None,
    ) -> np.ndarray:
        """Преобразование массива каналов (count, H, W) в RGBA uint8 (H, W, 4)."""
        count, h, w = data.shape

        if count == 1:
            gray = data[0].astype(np.float32)
            nodata_mask = np.zeros((h, w), dtype=bool)
            if nodata is not None:
                if np.issubdtype(data.dtype, np.floating) and math.isnan(nodata):
                    nodata_mask = np.isnan(gray)
                elif np.issubdtype(data.dtype, np.floating):
                    nodata_mask = np.isclose(gray, nodata)
                else:
                    nodata_mask = (data[0] == nodata)
            if mask is not None:
                nodata_mask = nodata_mask | (mask == 0)

            if np.issubdtype(data.dtype, np.floating):
                nodata_mask = nodata_mask | np.isnan(gray) | np.isinf(gray)

            valid = ~nodata_mask

            if data.dtype == np.uint8:
                gray_norm = data[0].copy()
            else:
                if np.any(valid):
                    valid_vals = gray[valid]
                    vmin = float(np.percentile(valid_vals, 2))
                    vmax = float(np.percentile(valid_vals, 98))
                    if vmax > vmin:
                        gray_norm = np.clip((gray - vmin) / (vmax - vmin) * 255.0, 0, 255).astype(np.uint8)
                    else:
                        gray_norm = np.full((h, w), 128, dtype=np.uint8)
                else:
                    gray_norm = np.zeros((h, w), dtype=np.uint8)

            alpha = np.where(valid, 255, 0).astype(np.uint8)
            return np.dstack([gray_norm, gray_norm, gray_norm, alpha])

        elif count == 3:
            # Определение RGB
            r_idx, g_idx, b_idx = 0, 1, 2
            if colorinterp and len(colorinterp) >= 3:
                ci_list = list(colorinterp)
                if ColorInterp.red in ci_list:
                    r_idx = ci_list.index(ColorInterp.red)
                if ColorInterp.green in ci_list:
                    g_idx = ci_list.index(ColorInterp.green)
                if ColorInterp.blue in ci_list:
                    b_idx = ci_list.index(ColorInterp.blue)

            r = data[r_idx]
            g = data[g_idx]
            b = data[b_idx]

            nodata_mask = np.zeros((h, w), dtype=bool)
            if nodata is not None:
                if np.issubdtype(data.dtype, np.floating) and math.isnan(nodata):
                    nodata_mask = np.isnan(r) | np.isnan(g) | np.isnan(b)
                elif np.issubdtype(data.dtype, np.floating):
                    nodata_mask = np.isclose(r, nodata) & np.isclose(g, nodata) & np.isclose(b, nodata)
                else:
                    nodata_mask = (r == nodata) & (g == nodata) & (b == nodata)

            if mask is not None:
                nodata_mask = nodata_mask | (mask == 0)

            if np.issubdtype(data.dtype, np.floating):
                nodata_mask = nodata_mask | np.isnan(r) | np.isnan(g) | np.isnan(b) | np.isinf(r) | np.isinf(g) | np.isinf(b)

            valid = ~nodata_mask

            def _norm_band(ch: np.ndarray) -> np.ndarray:
                if ch.dtype == np.uint8:
                    return ch
                ch_f = ch.astype(np.float32)
                if np.any(valid):
                    vals = ch_f[valid]
                    cmin = float(np.percentile(vals, 1))
                    cmax = float(np.percentile(vals, 99))
                    if cmax > cmin:
                        return np.clip((ch_f - cmin) / (cmax - cmin) * 255.0, 0, 255).astype(np.uint8)
                return np.clip(ch_f, 0, 255).astype(np.uint8)

            r_norm = _norm_band(r)
            g_norm = _norm_band(g)
            b_norm = _norm_band(b)
            alpha = np.where(valid, 255, 0).astype(np.uint8)
            return np.dstack([r_norm, g_norm, b_norm, alpha])

        else:
            # 4 или более каналов
            # Проверяем наличие явного альфа-канала
            has_explicit_alpha = False
            alpha_idx = -1
            if colorinterp and len(colorinterp) >= 4:
                for idx, ci in enumerate(colorinterp):
                    if ci == ColorInterp.alpha:
                        has_explicit_alpha = True
                        alpha_idx = idx
                        break

            r = data[0]
            g = data[1]
            b = data[2]

            nodata_mask = np.zeros((h, w), dtype=bool)
            if nodata is not None:
                if np.issubdtype(data.dtype, np.floating) and math.isnan(nodata):
                    nodata_mask = np.isnan(r) | np.isnan(g) | np.isnan(b)
                elif np.issubdtype(data.dtype, np.floating):
                    nodata_mask = np.isclose(r, nodata) & np.isclose(g, nodata) & np.isclose(b, nodata)
                else:
                    nodata_mask = (r == nodata) & (g == nodata) & (b == nodata)
            if mask is not None:
                nodata_mask = nodata_mask | (mask == 0)

            if np.issubdtype(data.dtype, np.floating):
                nodata_mask = nodata_mask | np.isnan(r) | np.isnan(g) | np.isnan(b) | np.isinf(r) | np.isinf(g) | np.isinf(b)

            valid = ~nodata_mask

            def _norm_band(ch: np.ndarray) -> np.ndarray:
                if ch.dtype == np.uint8:
                    return ch
                ch_f = ch.astype(np.float32)
                if np.any(valid):
                    vals = ch_f[valid]
                    cmin = float(np.percentile(vals, 1))
                    cmax = float(np.percentile(vals, 99))
                    if cmax > cmin:
                        return np.clip((ch_f - cmin) / (cmax - cmin) * 255.0, 0, 255).astype(np.uint8)
                return np.clip(ch_f, 0, 255).astype(np.uint8)

            r_norm = _norm_band(r)
            g_norm = _norm_band(g)
            b_norm = _norm_band(b)

            if has_explicit_alpha and alpha_idx >= 0:
                raw_a = data[alpha_idx]
                if raw_a.dtype == np.uint8:
                    alpha = raw_a.copy()
                else:
                    alpha = np.clip(raw_a.astype(np.float32) / (raw_a.max() or 1.0) * 255.0, 0, 255).astype(np.uint8)
                alpha = np.where(valid, alpha, 0).astype(np.uint8)
            else:
                alpha = np.where(valid, 255, 0).astype(np.uint8)

            return np.dstack([r_norm, g_norm, b_norm, alpha])

    def read_preview(
        self,
        path: Path | str,
        max_dimension: int = 4096,
        max_preview_dimension: int | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Чтение уменьшенного представления растра без перегрузки RAM."""
        if max_preview_dimension is not None:
            max_dimension = max_preview_dimension

        p = Path(path).resolve()
        cache_key = f"preview:{p}:{max_dimension}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        ds = self._get_dataset(p)

        full_w = ds.width
        full_h = ds.height
        max_dim = max(full_w, full_h)

        if max_dim <= max_dimension:
            out_w = full_w
            out_h = full_h
        else:
            scale = max_dimension / max_dim
            out_w = max(1, int(round(full_w * scale)))
            out_h = max(1, int(round(full_h * scale)))

        # Чтение с субдискретизацией
        data = ds.read(
            out_shape=(ds.count, out_h, out_w),
            resampling=Resampling.bilinear if (out_w < full_w) else Resampling.nearest,
        )

        try:
            mask = ds.read_masks(
                out_shape=(1, out_h, out_w),
                resampling=Resampling.nearest,
            )[0]
        except Exception:
            mask = None

        colorinterp = getattr(ds, "colorinterp", None)
        rgba = self._normalize_to_rgba(data, colorinterp, ds.nodata, mask)

        t = ds.transform
        meta = {
            "full_width": full_w,
            "full_height": full_h,
            "preview_width": out_w,
            "preview_height": out_h,
            "scale_x": full_w / out_w,
            "scale_y": full_h / out_h,
            "transform": (float(t.a), float(t.b), float(t.c), float(t.d), float(t.e), float(t.f)),
            "crs": ds.crs.to_string() if ds.crs else None,
            "bounds": (float(ds.bounds.left), float(ds.bounds.bottom), float(ds.bounds.right), float(ds.bounds.top)),
        }

        # Ограничение размера кэша
        if len(self._cache) >= self.MAX_CACHE_ENTRIES:
            oldest = next(iter(self._cache))
            del self._cache[oldest]

        self._cache[cache_key] = (rgba, meta)
        return rgba, meta

    def read_window(
        self,
        path: Path | str,
        map_extent: tuple[float, float, float, float],
        target_width: int | None = None,
        target_height: int | None = None,
        out_width: int | None = None,
        out_height: int | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]] | None:
        """Чтение заданного географического окна с субдискретизацией под целевой размер."""
        tw = out_width if out_width is not None else target_width
        th = out_height if out_height is not None else target_height
        if tw is None or th is None:
            raise ValueError("target_width and target_height must be specified")

        p = Path(path).resolve()
        ds = self._get_dataset(p)

        min_x, min_y, max_x, max_y = map_extent
        if max_x <= min_x or max_y <= min_y:
            return None

        # Преобразование географического охвата в окно пикселей
        try:
            req_window = from_bounds(min_x, min_y, max_x, max_y, transform=ds.transform)
        except Exception as e:
            logger.warning("Не удалось вычислить окно из охвата: %s", e)
            return None

        full_window = Window(0, 0, ds.width, ds.height)
        try:
            intersected = req_window.intersection(full_window)
        except Exception:
            return None

        # Округление окна до целых пикселей
        col_off = max(0, int(math.floor(intersected.col_off)))
        row_off = max(0, int(math.floor(intersected.row_off)))
        col_end = min(ds.width, int(math.ceil(intersected.col_off + intersected.width)))
        row_end = min(ds.height, int(math.ceil(intersected.row_off + intersected.height)))

        w = col_end - col_off
        h = row_end - row_off

        if w <= 0 or h <= 0:
            return None

        actual_window = Window(col_off, row_off, w, h)
        out_w = max(1, tw)
        out_h = max(1, th)

        data = ds.read(
            window=actual_window,
            out_shape=(ds.count, out_h, out_w),
            resampling=Resampling.bilinear,
        )

        try:
            mask = ds.read_masks(
                window=actual_window,
                out_shape=(1, out_h, out_w),
                resampling=Resampling.nearest,
            )[0]
        except Exception:
            mask = None

        colorinterp = getattr(ds, "colorinterp", None)
        rgba = self._normalize_to_rgba(data, colorinterp, ds.nodata, mask)

        win_transform = rasterio.windows.transform(actual_window, ds.transform)
        win_bounds = rasterio.windows.bounds(actual_window, ds.transform)

        meta = {
            "window": (col_off, row_off, w, h),
            "out_size": (out_w, out_h),
            "transform": (
                float(win_transform.a),
                float(win_transform.b),
                float(win_transform.c),
                float(win_transform.d),
                float(win_transform.e),
                float(win_transform.f),
            ),
            "bounds": win_bounds,
        }

        return rgba, meta

    def close(self, path: Path | str | None = None) -> None:
        """Освобождение файловых дескрипторов и очистка кэша."""
        if path is not None:
            p_key = str(Path(path).resolve())
            if p_key in self._open_datasets:
                ds = self._open_datasets.pop(p_key)
                try:
                    ds.close()
                except Exception:
                    pass
            # Очистка кэша для этого пути
            keys_to_del = [k for k in self._cache if p_key in k]
            for k in keys_to_del:
                del self._cache[k]
        else:
            for ds in self._open_datasets.values():
                try:
                    ds.close()
                except Exception:
                    pass
            self._open_datasets.clear()
            self._cache.clear()
        logger.debug("Освобождены дескрипторы растрового бэкенда для %s", path or "всех файлов")

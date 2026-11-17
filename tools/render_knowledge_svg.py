"""Render generated diagram SVGs with existing server librsvg/cairo libraries."""
from __future__ import annotations

import argparse
import ctypes as ct
import xml.etree.ElementTree as ET
from ctypes.util import find_library
from pathlib import Path


def render(svg, png, width=1800):
    root = ET.parse(svg).getroot()
    box = list(map(float, root.attrib["viewBox"].split()))
    scale = width / box[2]
    height = round(box[3] * scale)
    rsvg, cairo, objects = [ct.CDLL(find_library(name)) for name in ["rsvg-2", "cairo", "gobject-2.0"]]
    rsvg.rsvg_handle_new_from_file.argtypes = [ct.c_char_p, ct.c_void_p]
    rsvg.rsvg_handle_new_from_file.restype = ct.c_void_p
    rsvg.rsvg_handle_render_cairo.argtypes = [ct.c_void_p, ct.c_void_p]
    rsvg.rsvg_handle_render_cairo.restype = ct.c_int
    cairo.cairo_image_surface_create.argtypes = [ct.c_int, ct.c_int, ct.c_int]
    cairo.cairo_image_surface_create.restype = ct.c_void_p
    cairo.cairo_create.argtypes = [ct.c_void_p]
    cairo.cairo_create.restype = ct.c_void_p
    cairo.cairo_scale.argtypes = [ct.c_void_p, ct.c_double, ct.c_double]
    cairo.cairo_surface_write_to_png.argtypes = [ct.c_void_p, ct.c_char_p]
    cairo.cairo_surface_write_to_png.restype = ct.c_int
    cairo.cairo_destroy.argtypes = [ct.c_void_p]
    cairo.cairo_surface_destroy.argtypes = [ct.c_void_p]
    objects.g_object_unref.argtypes = [ct.c_void_p]
    handle = rsvg.rsvg_handle_new_from_file(str(Path(svg).resolve()).encode(), None)
    if not handle:
        raise RuntimeError("librsvg could not load diagram")
    surface = cairo.cairo_image_surface_create(0, width, height)
    context = cairo.cairo_create(surface)
    try:
        cairo.cairo_scale(context, scale, scale)
        if not rsvg.rsvg_handle_render_cairo(handle, context):
            raise RuntimeError("librsvg failed to render diagram")
        Path(png).parent.mkdir(parents=True, exist_ok=True)
        if cairo.cairo_surface_write_to_png(surface, str(Path(png).resolve()).encode()) != 0:
            raise RuntimeError("Could not save diagram preview")
    finally:
        cairo.cairo_destroy(context)
        cairo.cairo_surface_destroy(surface)
        objects.g_object_unref(handle)
    print(png)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svg", type=Path, required=True)
    parser.add_argument("--png", type=Path, required=True)
    parser.add_argument("--width", type=int, default=1800)
    args = parser.parse_args()
    if not 300 <= args.width <= 4000:
        parser.error("--width must be between 300 and 4000")
    render(args.svg, args.png, args.width)

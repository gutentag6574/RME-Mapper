"""English translations dictionary (en) for GeoPoint Mapper."""

TRANSLATIONS_EN: dict[str, str] = {
    # Application and general info
    "app.name": "GeoPoint Mapper",
    "app.title": "GeoPoint Mapper",
    "app.version_label": "Version {version}",
    "app.description": (
        "Geographic information application for working with point objects "
        "and georeferenced maps in GeoPackage format."
    ),
    "app.no_map": "No map loaded",

    # Top Menu
    "menu.file": "File",
    "menu.map": "Map",
    "menu.coordinates": "Coordinates",
    "menu.import": "Import",
    "menu.export": "Export",
    "menu.view": "View",
    "menu.settings": "Settings",
    "menu.language": "Language",
    "menu.help": "Help",

    # Actions
    "action.new_project": "New Project",
    "action.open_project": "Open Project...",
    "action.save": "Save",
    "action.save_as": "Save As...",
    "action.exit": "Exit",
    "action.open_map": "Open Map...",
    "action.close_map": "Close Map",
    "action.fit_map": "Fit Map",
    "action.add_point": "Add Point",
    "action.edit_point": "Edit",
    "action.delete_point": "Delete",
    "action.center_on_map": "Center on Map",
    "action.about": "About...",
    "action.view_toolbar": "Toolbar",
    "action.view_layers_points": "Layers and Points Panel",
    "action.view_properties": "Properties Panel",
    "action.view_statusbar": "Status Bar",

    # Tooltips
    "tooltip.open_map": "Open Map",
    "tooltip.open_project": "Open Project",
    "tooltip.save_project": "Save Project",
    "tooltip.add_point": "Add Point",
    "tooltip.fit_map": "Fit Map",

    # Panels
    "panel.layers": "Layers",
    "panel.points": "Points",
    "panel.properties": "Properties",

    # Point panel buttons
    "btn.add_point": "+ Add Point",
    "btn.edit_point": "Edit",
    "btn.delete_point": "Delete",

    # Empty startup overlay
    "startup.title": "GeoPoint Mapper",
    "startup.no_map": "No map loaded",
    "startup.instruction": "Open a georeferenced map\nto start working.",
    "startup.open_map_btn": "📂  Open Map...",

    # Status Bar
    "status.no_map": "No map loaded",
    "status.map_info": "Map: {name} | {crs} | Layers: {count}",
    "status.ready": "Ready",
    "status.crs": "CRS: {crs}",
    "status.points_count": "Points: {count}",
    "status.points_filtered": "Shown: {shown} of {total}",

    # Point Table and Counter
    "table.col_index": "#",
    "table.col_name": "Name",
    "table.col_lat": "Latitude",
    "table.col_lon": "Longitude",
    "table.col_shape": "Shape",
    "table.col_radius": "Radius",
    "points.count_total": "Points: {count}",
    "points.count_filtered": "Shown: {shown} of {total}",

    # Properties Panel
    "properties.empty_hint": "Select a point in the table to view its properties.",
    "properties.section_coords": "Coordinates",
    "properties.section_marker": "Marker",
    "properties.section_zone": "Zone",
    "properties.name": "Name:",
    "properties.latitude": "Latitude:",
    "properties.longitude": "Longitude:",
    "properties.shape": "Shape:",
    "properties.size": "Size:",
    "properties.color": "Color (RGB):",
    "properties.zone": "Zone:",
    "properties.radius": "Zone Radius:",
    "properties.zone_color": "Zone Color:",
    "properties.opacity": "Zone Opacity:",

    # Common words and buttons
    "common.yes": "Yes",
    "common.no": "No",
    "common.save": "Save",
    "common.add": "Add",
    "common.cancel": "Cancel",
    "common.close": "Close",
    "common.open": "Open",
    "common.warning": "Warning",
    "common.error": "Error",
    "common.info": "Information",
    "common.select_all": "Select All",
    "common.deselect_all": "Deselect All",
    "common.browse": "Browse...",

    # Units
    "unit.m": "m",
    "unit.km": "km",

    # Marker shapes
    "shape.circle": "Circle",
    "shape.square": "Square",
    "shape.triangle": "Triangle",

    # Layer roles
    "layer_role.boundary": "Boundary",
    "layer_role.roads": "Roads",
    "layer_role.places": "Places",
    "layer_role.waterways": "Waterways",
    "layer_role.water": "Water",
    "layer_role.layer": "Layer",

    # Point Dialog (PointDialog)
    "dialog.point.title_add": "Add Point",
    "dialog.point.title_edit": "Edit Point",
    "dialog.point.name": "Name:",
    "dialog.point.name_placeholder": "Name (optional)",
    "dialog.point.format": "Coordinate Format",
    "dialog.point.format_dd": "Decimal Degrees (DD)",
    "dialog.point.format_dms": "Degrees / Minutes / Seconds (DMS)",
    "dialog.point.lat_dd": "Latitude (DD):",
    "dialog.point.lon_dd": "Longitude (DD):",
    "dialog.point.dd_hint": "Range: latitude [-90; 90], longitude [-180; 180]",
    "dialog.point.lat_dms": "Latitude:",
    "dialog.point.lon_dms": "Longitude:",
    "dialog.point.degrees": "Degrees",
    "dialog.point.minutes": "Minutes",
    "dialog.point.seconds": "Seconds",
    "dialog.point.direction": "Dir.",
    "dialog.point.dms_hint": "Latitude: 0..90° [N/S], Longitude: 0..180° [E/W]. 15.2 and 15,2 are supported.",
    "dialog.point.style_box": "Marker Style",
    "dialog.point.shape": "Shape:",
    "dialog.point.size": "Size (px):",
    "dialog.point.color": "Color (RGB):",
    "dialog.point.choose_color": "Choose Color...",
    "dialog.point.preview": "Preview:",
    "dialog.point.zone_box": "Zone Around Point",
    "dialog.point.show_zone": "Show Zone",
    "dialog.point.radius": "Radius:",
    "dialog.point.radius_placeholder": "Example: 10 or 500",
    "dialog.point.zone_color": "Zone Color:",
    "dialog.point.opacity": "Opacity:",
    "dialog.point.btn_save": "Save",
    "dialog.point.btn_add": "Add",
    "dialog.point.btn_cancel": "Cancel",

    # Open Map Dialog (OpenMapDialog)
    "dialog.map.title": "Open Map — GeoPoint Mapper",
    "dialog.map.source_group": "Map Source",
    "dialog.map.source_file": "GeoPackage File (*.gpkg)",
    "dialog.map.source_catalog": "Profile Catalog",
    "dialog.map.file": "File:",
    "dialog.map.file_placeholder": "Specify path to *.gpkg file...",
    "dialog.map.browse": "Browse...",
    "dialog.map.crs_info": "CRS: {crs}",
    "dialog.map.layers_box": "GeoPackage Layers to Display",
    "dialog.map.col_check": "",
    "dialog.map.col_name": "Layer",
    "dialog.map.col_geom": "Geometry Type",
    "dialog.map.col_features": "Features",
    "dialog.map.working_boundary": "Working Boundary (optional):",
    "dialog.map.no_boundary": "— Do not use boundary —",
    "dialog.map.catalog_profiles": "Available Map Profiles:",
    "dialog.map.btn_open": "Open Map",
    "dialog.map.btn_cancel": "Cancel",

    # About Dialog (AboutDialog)
    "dialog.about.title": "About — {app_name}",
    "dialog.about.version": "Version {version}",
    "dialog.about.author": "Author and Developer:",
    "dialog.about.telegram": "Telegram:",
    "dialog.about.email": "Email:",
    "dialog.about.close": "Close",

    # Validation errors: DD Coordinates
    "val.coord.expected_str_num": "Expected string or number, got: {type}",
    "val.coord.empty_coord": "Coordinate value cannot be empty",
    "val.coord.invalid_number_format": "Invalid number format: '{value}'",
    "val.coord.lat_range": "Latitude must be between -90 and 90 degrees. Got: {value}",
    "val.coord.lon_range": "Longitude must be between -180 and 180 degrees. Got: {value}",

    # Validation errors: DMS Coordinates
    "val.dms.enter_component": "Enter {component} of {coord_label}. For zero specify 0.",
    "val.dms.component_must_be_int": "{component} of {coord_label} must be an integer.",
    "val.dms.seconds_must_be_number": "Seconds of {coord_label} must be a number.",
    "val.dms.lat_deg_range": "Latitude degrees must be between 0 and 90. Got: {value}",
    "val.dms.lat_min_range": "Latitude minutes must be between 0 and 59.",
    "val.dms.lat_sec_negative": "Latitude seconds cannot be negative.",
    "val.dms.lat_sec_less_60": "Latitude seconds must be less than 60.",
    "val.dms.lat_90_zero": "At latitude 90 degrees, minutes and seconds must be 0.",
    "val.dms.lat_dir_str": "Latitude direction must be a string (N or S).",
    "val.dms.lat_dir_invalid": "Only N and S directions are valid for latitude. Got: '{value}'",
    "val.dms.lon_deg_range": "Longitude degrees must be between 0 and 180. Got: {value}",
    "val.dms.lon_min_range": "Longitude minutes must be between 0 and 59.",
    "val.dms.lon_sec_negative": "Longitude seconds cannot be negative.",
    "val.dms.lon_sec_less_60": "Longitude seconds must be less than 60.",
    "val.dms.lon_180_zero": "At longitude 180 degrees, minutes and seconds must be 0.",
    "val.dms.lon_dir_str": "Longitude direction must be a string (E or W).",
    "val.dms.lon_dir_invalid": "Only E and W directions are valid for longitude. Got: '{value}'",

    # Validation errors: Marker style
    "val.style.symbol_str": "Marker shape must be a string. Got: {type}",
    "val.style.symbol_unknown": "Invalid marker shape: '{value}'. Allowed: {allowed}",
    "val.style.size_empty": "Marker size cannot be empty.",
    "val.style.size_format": "Marker size must be a number from {min} to {max} px.",
    "val.style.size_number": "Marker size must be a number.",
    "val.style.size_range": "Marker size must be in range from {min} to {max} px. Got: {value}",
    "val.style.rgb_empty": "Color component {component} cannot be empty.",
    "val.style.rgb_format": "Color component {component} must be an integer from 0 to 255.",
    "val.style.rgb_int": "Color component {component} must be an integer.",
    "val.style.rgb_range": "Color component {component} must be in range from 0 to 255. Got: {value}",

    # Validation errors: Radius zone
    "val.zone.radius_empty": "Zone radius cannot be empty.",
    "val.zone.radius_format": "Invalid radius format: '{value}'. Expected number.",
    "val.zone.radius_type": "Invalid radius type: {type}",
    "val.zone.radius_positive": "Zone radius must be greater than 0. Got: {value}",
    "val.zone.radius_range": "Zone radius must be in range from 1 m to 1 000 000 m (1000 km). Got: {value}",
    "val.zone.opacity_empty": "Zone opacity cannot be empty.",
    "val.zone.opacity_number": "Zone opacity must be a number from 0 to 100.",
    "val.zone.opacity_range": "Zone opacity must be in range from 0% to 100%. Got: {value}",

    # System messages, warnings, confirmations
    "msg.outside_map_warning": "The coordinate is outside the working area of map \"{name}\". Save the point?",
    "msg.point_outside_title": "Point Outside Working Area",
    "msg.unsaved_changes": "Save changes before exiting?",
    "msg.unsaved_title": "Unsaved Changes",
    "msg.delete_point_confirm": "Are you sure you want to delete point \"{name}\"?",
    "msg.delete_point_title": "Delete Point",
    "msg.close_map_confirm": (
        "There are user points in the project ({count}).\n"
        "Close map? Project points will remain in model and be hidden until a new map is loaded."
    ),
    "msg.close_map_title": "Close Map",
    "msg.project_not_found": "Project file not found: {path}",
    "msg.corrupt_json": "Project JSON file is corrupted.",
    "msg.unsupported_format": "Unsupported project format.",
    "msg.newer_version": "Project file was created in a newer version of the program.",
    "msg.map_not_found": "Map file not found: {path}",
    "msg.save_failed": "Failed to save project: {error}",
    "msg.open_failed": "Failed to open project: {error}",
    "msg.cannot_open_gpkg": "Cannot open GeoPackage: {path}",
    "msg.layer_not_found": "Layer not found: {layer}",
    "msg.crs_undefined": "Map CRS is undefined.",
    "msg.no_layers_selected": "No layers selected for opening.",
    "msg.unsupported_source": "Unsupported map source.",
    "msg.new_project_unsaved": "Current project contains unsaved changes.\nSave before creating a new project?",
    "msg.open_project_unsaved": "Current project contains unsaved changes.\nSave before opening another project?",
    "msg.save_filter_gpmap": "GeoPoint Mapper Projects (*.gpmap);;All Files (*.*)",
    "msg.open_filter_projects": "GeoPoint Mapper Projects (*.gpmap *.rmeproject);;All Files (*.*)",
    "msg.open_filter_gpkg": "GeoPackage Files (*.gpkg);;All Files (*.*)",

    # Project and state
    "project.untitled": "Untitled",
    "point.default_name_prefix": "Point",

    # Dialogs and file filters
    "dialog.no_map_title": "Map Not Loaded",
    "dialog.no_map_text": "Please open a map first before adding points.",
    "dialog.close_map_title": "Close Map",
    "dialog.close_map_text": (
        "The project contains user points ({count}).\n"
        "Close map? Project points will remain in the model and be hidden until a new map is loaded."
    ),
    "dialog.unsaved_title": "Unsaved Changes",
    "dialog.unsaved_text": "Save changes to project '{name}' before {action}?",
    "dialog.unsaved_action_exit": "exiting",
    "dialog.unsaved_action_new": "creating a new project",
    "dialog.unsaved_action_open": "opening another project",
    "dialog.save_project_title": "Save Project",
    "dialog.open_project_title": "Open Project",
    "dialog.open_project_error_title": "Error Opening Project",
    "dialog.error_title": "Error",
    "dialog.map_not_found_title": "Map File Not Found",
    "dialog.map_not_found_text": "Map file '{name}' not found.\nWhat would you like to do?",
    "dialog.map_not_found_find": "Locate map...",
    "dialog.map_not_found_open_without": "Open project without map",
    "dialog.locate_map_title": "Locate Map File",
    "btn.cancel": "Cancel",

    "filter.project_files": "GeoPoint Mapper Project (*.gpmap);;RME-Mapper Project (*.rmeproject);;All Files (*.*)",
    "filter.project_files_all": "GeoPoint Mapper Projects (*.gpmap *.rmeproject);;GeoPoint Mapper Project (*.gpmap);;RME-Mapper Project (*.rmeproject);;All Files (*.*)",
    "filter.geopackage_files": "GeoPackage Files (*.gpkg);;All Files (*.*)",

    # Status messages
    "status.point_added": "Point added: {name}",
    "status.point_updated": "Point updated: {name}",
    "status.point_deleted": "Point deleted",
    "status.focus_point": "Focus on point: {name}",
    "status.project_saved": "Project saved: {path}",
    "status.project_opened": "Project opened: {name}",
    "status.error_map_not_found": "Error: map file not found",
    "status.error_no_layers": "Error: no supported layers found",

    # Additional error messages
    "msg.save_project_error": "Failed to save project:\n{err}",
    "msg.open_project_error": "Failed to open project file:\n{path}\n\n{err}",
    "msg.map_file_not_found": "Map file not found",
    "msg.no_layers_found": "No supported map layers found in source",

    # Stage 12.2: Recent files, search, coordinates, safety
    "menu.recent_projects": "Recent Projects",
    "menu.recent_maps": "Recent Maps",
    "menu.clear_recent": "Clear List",
    "menu.no_recent": "(no recent files)",
    "msg.file_no_longer_exists": "The file no longer exists.",
    "search.placeholder": "Search...",
    "action.copy_coordinates": "Copy Coordinates",
    "action.copy_dd": "DD",
    "action.copy_dms": "DMS",
    "action.copy_map_xy": "Map X/Y",
    "status.coords_copied": "Coordinates copied.",
    "dialog.confirm_delete_title": "Delete Point",
    "dialog.confirm_delete_text": "Delete selected point?",
    "dialog.recovery_title": "Crash Recovery",
    "dialog.recovery_text": "An unsaved recovery snapshot from a previous session was found.\nRestore it?",
    "dialog.recovery_corrupt_title": "Recovery Error",
    "dialog.recovery_corrupt_text": "Recovery snapshot is corrupt and cannot be read.\nDiscard it?",
    "btn.restore": "Restore",
    "btn.discard": "Discard",
    "dialog.drop_title": "Drag & Drop",
    "msg.drop_multiple": "Multiple files dropped. Only opening the first file:\n{path}",
    "msg.drop_unsupported": "Unsupported file format: {ext}",
}



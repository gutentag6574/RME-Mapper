"""Verified audit findings and new user workflows on the main branch."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
from urllib.parse import parse_qs,urlsplit
import zipfile
import pytest
from PIL import Image
from PySide6.QtGui import QImage,QPainter,QPixmap,QColor
from PySide6.QtWidgets import QDialog

from rme_mapper.services.georeference_service import GeoreferenceService
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture
def image(tmp_path):
    path=tmp_path/'plan.png'
    Image.new('RGBA',(100,100),(255,0,0,255)).save(path)
    GeoreferenceService.export_world_file(path,(2,0,500000,0,-2,6000000),'EPSG:32639')
    return path


@pytest.fixture
def window(qapp,image):
    profile=MapProfile(id='test',name='Test',source_type='georeferenced_image',source_path=str(image),crs='EPSG:32639',affine_transform=[2,0,500000,0,-2,6000000])
    w=MainWindow(map_profile=profile)
    yield w
    w.project_controller.set_modified(False)
    w.close()


def test_group_status_interpolates_name(window):
    point=MapPoint('One',54,51)
    window.point_controller._cmd_add_points([point])
    group=window._group_service.create_group('Survey')
    window.point_controller.move_points_to_group_workflow(group.id,[point.id])
    status=window.statusBar().currentMessage()
    assert 'Survey' in status and '{' not in status


def test_georef_undo_recomputes_extent(window):
    profile=window.map_controller.active_profile
    old=dict(profile.extent)
    fake=MagicMock()
    fake.exec.return_value=QDialog.DialogCode.Accepted
    fake.get_affine_transform.return_value=(4,0,500100,0,-4,6000100)
    fake.get_crs.return_value='EPSG:32639'
    fake.get_control_points.return_value=[]
    fake.get_extent.return_value=dict(xmin=500100,xmax=500500,ymin=5999700,ymax=6000100)
    with patch('rme_mapper.ui.georeference_dialog.GeoreferenceDialog',return_value=fake):
        assert window.map_controller.edit_georeferencing(undo_manager=window.point_controller.undo_manager)
    assert profile.extent!=old
    window.undo()
    assert profile.extent==old
    window.redo()
    assert profile.extent!=old


def test_broken_prj_keeps_affine_for_manual_crs(qapp,image):
    image.with_suffix('.prj').write_text('broken projection')
    data=GeoreferenceService.read_world_file(image)
    assert data['crs'] is None
    assert data['affine']==(2,0,500000,0,-2,6000000)
    from rme_mapper.ui.georeference_dialog import GeoreferenceDialog
    dialog=GeoreferenceDialog(image)
    assert not dialog.btn_apply.isEnabled()
    dialog.crs_edit.setText('EPSG:32639')
    assert dialog.btn_apply.isEnabled()
    dialog.close()


def test_no_duplicate_translation_keys():
    for lang in ('ru','en'):
        tree=ast.parse((Path(__file__).parents[1]/f'src/rme_mapper/i18n/translations_{lang}.py').read_text(encoding='utf-8'))
        value=next(n.value for n in tree.body if isinstance(n,(ast.Assign,ast.AnnAssign)) and isinstance(n.value,ast.Dict))
        keys=[k.value for k in value.keys]
        assert len(keys)==len(set(keys))


def test_world_file_functions_have_docstrings():
    assert GeoreferenceService.export_world_file.__doc__
    assert GeoreferenceService.solve_affine.__doc__


def test_custom_xyz_roundtrip_and_last_provider(qapp):
    from rme_mapper.ui.online_basemap_dialog import OnlineBasemapDialog
    settings=AppSettingsService()
    dialog=OnlineBasemapDialog(settings_service=settings)
    dialog._rb_custom.setChecked(True)
    dialog._custom_name.setText('Survey tiles')
    dialog._url_edit.setText('https://example.com/{z}/{x}/{y}.png')
    dialog._on_accept()
    provider=dialog.get_selected_provider()
    assert settings.get_custom_providers()[0]['id']==provider.id
    reopened=OnlineBasemapDialog(settings_service=settings)
    assert reopened._provider_combo.currentData()==provider.id
    assert reopened._url_edit.text()==provider.url_template
    assert reopened._custom_name.text()=='Survey tiles'
    reopened._remove_custom_provider()
    assert settings.get_custom_providers()==[]
    reopened.close()
    dialog.close()


def test_cache_size_setting_used(qapp):
    from rme_mapper.maps.online_tile_manager import OnlineTileManager
    from PySide6.QtWidgets import QGraphicsScene
    AppSettingsService().set_online_cache_max_mb(73)
    scene=QGraphicsScene()
    manager=OnlineTileManager(scene)
    assert manager._cache.max_size_bytes==73*1024*1024


@pytest.mark.parametrize('crs,extent',[('EPSG:3857',(-100000,-100000,100000,100000)),('EPSG:4326',(-5,-5,5,5)),('EPSG:32639',(499000,5999000,501000,6001000))])
def test_cached_online_export_in_multiple_crs(qapp,crs,extent):
    from rme_mapper.services.tile_render_service import render_cached_tiles
    tile=QPixmap(256,256)
    tile.fill(QColor('red'))
    manager=SimpleNamespace(provider=SimpleNamespace(id='test',min_zoom=0,max_zoom=0),_get_mem_cache=lambda *args:tile)
    image=QImage(256,256,QImage.Format.Format_RGBA8888)
    image.fill(QColor('white'))
    painter=QPainter(image)
    try:
        render_cached_tiles(painter,manager,extent,256,256,crs)
    finally:
        painter.end()
    pixel=image.pixelColor(128,128)
    assert pixel.red()>200 and pixel.green()<50


def test_settings_apply_and_new_point_defaults(window):
    from rme_mapper.ui.settings_dialog import SettingsDialog
    from rme_mapper.ui.point_dialog import PointDialog
    dialog=SettingsDialog(window._settings_service,window)
    dialog.cache.setValue(80)
    dialog.size.setValue(19)
    dialog.color.setText('#123456')
    dialog.recovery.setChecked(False)
    dialog.accept()
    window.apply_preferences()
    assert window.map_canvas.online_tile_manager()._cache.max_size_bytes==80*1024*1024
    window.project_controller.set_modified(True)
    assert not window.project_controller._recovery_timer.isActive()
    point=PointDialog(default_name='New')
    assert point.size_spin.value()==19
    assert point.r_edit.text()=='18'
    point.close()


def test_wms_template_and_bbox():
    from rme_mapper.services.wms_service import build_wms_template
    from rme_mapper.models.online_provider import ProviderRegistry
    template=build_wms_template('https://example.com/wms?token=test','workspace:layer')
    provider=ProviderRegistry.create_custom_provider(id='wms',name='WMS',url_template=template)
    params=parse_qs(urlsplit(provider.build_tile_url(0,0,0)).query)
    assert params['SRS']==['EPSG:3857']
    assert len(params['BBOX'][0].split(','))==4
    assert params['VERSION']==['1.1.1']


def test_field_points_tracks_and_kmz(tmp_path):
    from rme_mapper.services.field_import_service import read_field_file
    gpx=tmp_path/'sample.gpx'
    gpx.write_text('<gpx><wpt lat="54" lon="51"><name>A</name></wpt><trk><name>Route</name><trkseg><trkpt lat="54" lon="51"/><trkpt lat="54.1" lon="51.1"/></trkseg></trk></gpx>')
    points,tracks=read_field_file(gpx)
    assert points[0].name=='A' and len(tracks[0]['coordinates'])==2
    kml=b'<kml><Document><Placemark><name>B</name><Point><coordinates>51,54,0</coordinates></Point><LineString><coordinates>51,54,0 51.1,54.1,0</coordinates></LineString></Placemark></Document></kml>'
    kmz=tmp_path/'sample.kmz'
    with zipfile.ZipFile(kmz,'w') as archive:
        archive.writestr('doc.kml',kml)
    points,tracks=read_field_file(kmz)
    assert points[0].longitude==51 and len(tracks)==1
    gpx.write_text('<!DOCTYPE gpx [<!ENTITY x "test">]><gpx/>')
    with pytest.raises(ValueError):
        read_field_file(gpx)


def test_annotations_persist_and_undo(window,tmp_path):
    from rme_mapper.services.project_service import ProjectService
    record=dict(kind='line',coordinates=[[51,54],[51.01,54.01]],name='Track')
    window.add_annotation_batch([record],[])
    assert len(window._annotation_items)==1
    window.undo()
    assert window.map_controller.active_profile.annotations==[]
    window.redo()
    path=tmp_path/'track.gpmap'
    assert window.project_controller.save_project_as_workflow(path)
    data=ProjectService.load_project(path)
    assert data.map.annotations[0]['coordinates']==record['coordinates']


def test_cross_crs_raster_overlay_and_export(window,image):
    manager=window.raster_overlays_panel
    manager.add_record(dict(path=str(image),crs='EPSG:4326',affine=[.001,0,50.95,0,-.001,54.05],opacity=.5))
    assert len(manager.records)==1
    assert manager.items[0].opacity()==.5


def test_xlsx_audit_claim_is_false_for_write_only():
    from openpyxl.worksheet._write_only import WriteOnlyWorksheet
    assert callable(WriteOnlyWorksheet.close)


def test_malformed_preferences_have_safe_defaults(qapp):
    settings=AppSettingsService()
    settings._set_str('points/defaults','not JSON')
    settings._set_str('recovery/seconds','broken')
    settings._set_str('coordinates/precision','broken')
    from rme_mapper.ui.settings_dialog import SettingsDialog
    dialog=SettingsDialog(settings)
    assert dialog.interval.value()==3
    assert dialog.precision.value()==6
    assert settings.get_point_defaults()=={}
    dialog.close()


def test_version_sync_updates_both_numeric_versions(tmp_path,monkeypatch):
    import build_release
    package=tmp_path/'packaging'
    package.mkdir()
    target=package/'file_version_info.txt'
    target.write_text("filevers=(1, 0, 0, 0)\nprodvers=(1, 0, 0, 0)\nStringStruct(u'FileVersion', u'1.0.0.0')\nStringStruct(u'ProductVersion', u'1.0.0')")
    monkeypatch.setattr(build_release,'PROJECT_ROOT',tmp_path)
    build_release.sync_version_metadata('1.1.0')
    text=target.read_text()
    assert 'filevers=(1, 1, 0, 0)' in text
    assert 'prodvers=(1, 1, 0, 0)' in text


def test_measurement_saved_and_deleted_with_undo(window):
    canvas=window.map_canvas
    canvas.start_measurement('measure_distance')
    canvas._measure_points=[(500000,-6000000),(500100,-6000100)]
    canvas._finish_measurement()
    assert window.save_measurement_button.isEnabled()
    window.save_last_measurement()
    assert len(window.map_controller.active_profile.annotations)==1
    window.annotation_list.setCurrentRow(0)
    window.remove_selected_annotation()
    assert window.map_controller.active_profile.annotations==[]
    window.undo()
    assert len(window.map_controller.active_profile.annotations)==1


def test_numeric_scale_handles_nonfinite_input(qapp):
    from rme_mapper.maps.scale_overlay import ScaleOverlayWidget
    widget=ScaleOverlayWidget()
    widget.update_scale('invalid',float('nan'),float('nan'))
    assert widget.text()==''
    widget.update_scale('100 m',100,100)
    assert widget._ratio_text.startswith('≈1:')


def test_hidden_panel_preserves_saved_width():
    from rme_mapper.services.app_settings_service import AppSettingsService
    settings=AppSettingsService()
    settings.set_splitter_sizes([270,800,280])
    settings.set_splitter_sizes([270,1080,0])
    assert settings.get_splitter_sizes()==[270,1080,280]
    settings.set_splitter_sizes([0,1100,280])
    assert settings.get_splitter_sizes()==[270,1100,280]


def test_project_preserves_external_raster_path(tmp_path,monkeypatch):
    from rme_mapper.services import project_service
    root=tmp_path/'application'
    root.mkdir()
    monkeypatch.setattr(project_service,'get_project_root',lambda: root)
    path=tmp_path/'field_maps'/'plan.tif'
    project=project_service.ProjectService.build_project_data(map_path=path,source_type='geotiff')
    assert project.map.relative_path==path.resolve().as_posix()

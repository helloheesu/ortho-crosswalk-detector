"""Header-only discovery and bounded preview/window reads; originals are read-only."""
import hashlib
import io
import json
import math
import warnings
from pathlib import Path
import numpy as np
import rasterio
from affine import Affine
from PIL import Image
from rasterio.enums import Resampling, ColorInterp
from rasterio.windows import Window
from .geo import to_map, pixel_polygon
from shapely.geometry import mapping

EXTS={'.tif','.tiff','.png','.jpg','.jpeg','.jp2'}


def scan(root):
    root=Path(root).resolve()
    if not root.is_dir():
        raise ValueError('입력 폴더가 없습니다')
    out=[]
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.suffix.lower() not in EXTS or not path.resolve().is_relative_to(root):
            continue
        stat=path.stat()
        identity=f'{path.relative_to(root)}:{stat.st_size}:{stat.st_mtime_ns}'
        item={'id':hashlib.sha256(identity.encode()).hexdigest()[:24], 'relative_path':str(path.relative_to(root)),
              'bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns,'set':str(path.relative_to(root).parent),
              'sidecars':[],'georef':None,'warning':None}
        sidecars=[p for p in path.parent.iterdir() if p.is_file() and p!=path and p.name.lower().startswith(path.stem.lower()+'.') and p.suffix.lower() not in EXTS]
        sidecars=[p for p in sidecars if p.resolve().is_relative_to(root)]
        item['sidecars']=[str(p.relative_to(root)) for p in sidecars]
        item['sidecar_stats']={str(p.relative_to(root)):[p.stat().st_size,p.stat().st_mtime_ns] for p in sidecars}
        item['id']=hashlib.sha256((identity+json.dumps(item['sidecar_stats'],sort_keys=True)).encode()).hexdigest()[:24]
        item['xml_metadata']=[]
        for side in sidecars:
            if side.suffix.lower()=='.xml' and side.stat().st_size<=2_000_000:
                import xml.etree.ElementTree as ET
                try:
                    tree=ET.parse(side)
                    item['xml_metadata'].append({'path':str(side.relative_to(root)),'fields':[{'tag':node.tag.split('}')[-1],'text':node.text.strip()[:1000]} for node in tree.iter() if len(node)==0 and node.text and node.text.strip()][:300],'interpretation':'출처·해상도·촬영 정보 참고. XML 영역을 픽셀 변환으로 추정하지 않음.'})
                except ET.ParseError as e:
                    item['xml_metadata'].append({'path':str(side.relative_to(root)),'error':str(e)})
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',rasterio.errors.NotGeoreferencedWarning)
                with rasterio.open(path) as ds:
                    crs=ds.crs; a=ds.transform
                    # GDAL reads TFW automatically. A matching PRJ supplies CRS only,
                    # never invents a pixel origin from a sheet name or XML extent.
                    prj=next((p for p in sidecars if p.suffix.lower()=='.prj'),None)
                    if not crs and prj:
                        crs=rasterio.crs.CRS.from_wkt(prj.read_text())
                    meta=path.with_suffix(path.suffix+'.meta.json')
                    metadata=json.loads(meta.read_text()) if meta in sidecars else {}
                    if metadata.get('crs') and not crs:
                        crs=rasterio.crs.CRS.from_user_input(metadata['crs'])
                    if metadata.get('transform') is not None:
                        a=Affine(*metadata['transform'])
                    g=None
                    if crs and a!=Affine.identity() and abs(a.determinant)>1e-15:
                        g={'crs':str(crs),'transform':list(a)[:6],'method':'raster/sidecar metadata','verified':False,'absolute_accuracy_m':None}
                    item.update(width=ds.width,height=ds.height,bands=ds.count,dtype=ds.dtypes[0],
                                resolution=list(ds.res) if g and not metadata.get('transform') else ([math.hypot(a.a,a.d),math.hypot(a.b,a.e)] if g else None),
                                resolution_units=crs.linear_units if crs and crs.is_projected else ('degrees' if crs else None),
                                georef=g,metadata=metadata,driver=ds.driver,overviews=ds.overviews(1))
                    if g:
                        item['footprint']=mapping(to_map(pixel_polygon([0,0,ds.width,ds.height]),g))
                    else:
                        item['footprint']=None
                        item['warning']='좌표계 또는 픽셀 변환 없음. 픽셀 검수 가능, 지도 위치 미확정.'
        except Exception as exc:
            item['error']=str(exc)
        out.append(item)
    return out


def image_path(root,item):
    p=(Path(root)/item['relative_path']).resolve()
    if not p.is_relative_to(Path(root).resolve()) or not p.is_file():
        raise ValueError('입력 경로 오류')
    s=p.stat()
    for rel,expected in item.get('sidecar_stats',{}).items():
        side=(Path(root)/rel).resolve()
        if not side.is_relative_to(Path(root).resolve()) or not side.is_file() or [side.stat().st_size,side.stat().st_mtime_ns]!=expected:
            raise ValueError('연결된 메타데이터가 변경되었습니다. 목록을 다시 읽으세요')
    if s.st_size!=item['bytes'] or s.st_mtime_ns!=item['mtime_ns']:
        raise ValueError('입력이 변경되었습니다. 목록을 다시 읽으세요')
    return p


def rgb(ds, window, max_size=None):
    w,h=window.width,window.height
    factor=min(1,max_size/max(w,h)) if max_size else 1
    shape=(max(1,round(h*factor)),max(1,round(w*factor)))
    colors=list(ds.colorinterp)
    indexes=[colors.index(c)+1 for c in (ColorInterp.red,ColorInterp.green,ColorInterp.blue)] if all(c in colors for c in (ColorInterp.red,ColorInterp.green,ColorInterp.blue)) else ([1,2,3] if ds.count>=3 else [1])
    arr=ds.read(indexes,window=window,out_shape=(len(indexes),*shape),resampling=Resampling.nearest,masked=True)
    mask=np.any(np.ma.getmaskarray(arr),axis=0)
    arr=arr.filled(0)
    if arr.dtype!=np.uint8:
        # Fixed dtype scale, recorded in manifests; no per-tile contrast variation.
        upper=np.iinfo(arr.dtype).max if np.issubdtype(arr.dtype,np.integer) else 1.0
        arr=np.clip(arr.astype(float)/upper*255,0,255).astype('uint8')
    if len(arr)==1:
        arr=np.repeat(arr,3,axis=0)
    result=np.moveaxis(arr,0,-1).copy(); result[mask]=0
    return result, float(np.mean(mask))


def preview(root,item,box=None,size=1400):
    b=box or [0,0,item['width'],item['height']]
    validate_box(b,item)
    with rasterio.open(image_path(root,item)) as ds:
        arr,_=rgb(ds,Window(b[0],b[1],b[2]-b[0],b[3]-b[1]),size)
    stream=io.BytesIO(); Image.fromarray(arr).save(stream,format='PNG')
    return stream.getvalue()


def validate_box(b,item):
    if len(b)!=4 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in b) or not (0<=b[0]<b[2]<=item['width'] and 0<=b[1]<b[3]<=item['height']):
        raise ValueError('원본 픽셀 범위 안의 [left,top,right,bottom]이 필요합니다')
    return list(b)


def fingerprint(root, item):
    """Hash only a selected source and its linked sidecars, never all holdings."""
    from .records import digest
    path = image_path(root, item)
    sidecars = []
    for relative in item['sidecars']:
        side = (Path(root) / relative).resolve()
        if not side.is_relative_to(Path(root).resolve()):
            raise ValueError('연결된 메타데이터 경로 오류')
        sidecars.append({'relative_path': relative, 'sha256': digest(side)})
    result = {'relative_path': item['relative_path'], 'sha256': digest(path),
              'sidecars': sidecars, 'source_metadata': item.get('metadata', {}),
              'bytes': item['bytes']}
    image_path(root, item)
    return result

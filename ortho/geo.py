import math
import numpy as np
from affine import Affine
from pyproj import CRS, Transformer
from shapely.geometry import Polygon, shape, mapping
from shapely import transform as shapely_transform

def geom_transform(function, geometry):
    return shapely_transform(geometry, function, interleaved=False)


def project(geometry, source, target):
    return geom_transform(Transformer.from_crs(source, target, always_xy=True).transform, geometry)


def polygon(data):
    g = shape(data)
    if g.geom_type != 'Polygon' or not g.is_valid or g.is_empty or g.area <= 0:
        raise ValueError('유효한 면적의 다각형이 필요합니다')
    if not all(math.isfinite(v) for xy in g.exterior.coords for v in xy):
        raise ValueError('유한 좌표가 필요합니다')
    return g


def pixel_polygon(box):
    l,t,r,b = box
    return Polygon([(l,t),(r,t),(r,b),(l,b)])


def to_map(g, georef):
    a = Affine(*georef['transform'])
    # Densify edges before changing projections (including long raster edges).
    g = g.segmentize(max(g.bounds[2]-g.bounds[0], g.bounds[3]-g.bounds[1])/32 or 1)
    return project(geom_transform(lambda x,y: (a.a*x+a.b*y+a.c, a.d*x+a.e*y+a.f), g), georef['crs'], 'EPSG:4326')


def to_pixel(g, georef):
    a = ~Affine(*georef['transform'])
    p = project(g.segmentize(max(g.bounds[2]-g.bounds[0],g.bounds[3]-g.bounds[1])/32 or 1), 'EPSG:4326', georef['crs'])
    return geom_transform(lambda x,y: (a.a*x+a.b*y+a.c, a.d*x+a.e*y+a.f), p)


def fit(points, width, height):
    if len(points)>500:
        raise ValueError('기준점은 최대 500개입니다')
    for p in points:
        x,y=p['pixel']; lon,lat=p['map']
        if not all(math.isfinite(v) for v in (x,y,lon,lat)) or not (0<=x<=width and 0<=y<=height and -180<=lon<=180 and -80<=lat<=84):
            raise ValueError('기준점 범위 오류 (위도 -80~84 지원)')
        if p['role'] not in ('fit','check'):
            raise ValueError('기준점 역할은 fit 또는 check입니다')
    train=[p for p in points if p['role']=='fit']
    if len(train)<3:
        raise ValueError('서로 일직선이 아닌 맞춤용 기준점 3쌍 이상이 필요합니다')
    lon,lat=np.mean([p['map'] for p in train],axis=0)
    zone=min(60,max(1,int((lon+180)//6)+1))
    crs=CRS.from_epsg((32600 if lat>=0 else 32700)+zone)
    tr=Transformer.from_crs(4326,crs,always_xy=True)
    design=np.array([[p['pixel'][0]/width,p['pixel'][1]/height,1] for p in train])
    targets=np.array([tr.transform(*p['map']) for p in train])
    coefs,_,rank,_=np.linalg.lstsq(design,targets,rcond=None)
    if rank<3 or np.linalg.cond(design)>1e8:
        raise ValueError('맞춤점이 일직선이거나 불안정합니다')
    a=Affine(coefs[0,0]/width,coefs[1,0]/height,coefs[2,0],coefs[0,1]/width,coefs[1,1]/height,coefs[2,1])
    if abs(a.determinant)<1e-12:
        raise ValueError('지도 기준점이 일직선이거나 겹칩니다')
    errors=[]
    for p in points:
        pred=(a.a*p['pixel'][0]+a.b*p['pixel'][1]+a.c,a.d*p['pixel'][0]+a.e*p['pixel'][1]+a.f); actual=tr.transform(*p['map'])
        errors.append(dict(p,error_m=math.dist(pred,actual)))
    def rmse(role):
        vals=[p['error_m']**2 for p in errors if p['role']==role]
        return math.sqrt(sum(vals)/len(vals)) if vals else None
    from shapely.geometry import MultiPoint
    hull=MultiPoint([p['pixel'] for p in train]).convex_hull
    return {'crs':crs.to_string(),'transform':list(a)[:6],'method':'affine least squares / local UTM',
            'points':errors,'fit_rmse_m':rmse('fit'),'check_rmse_m':rmse('check'),
            'fit_hull_pixels':mapping(hull),'extrapolation_outside_fit_hull':not hull.covers(pixel_polygon([0,0,width,height])),
            'absolute_accuracy_m':None,'accuracy_note':'기준 지도 자체의 오차는 미확인. 잔차는 실제 위치 정확도가 아닙니다.'}

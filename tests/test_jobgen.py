import json
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from ortho.jobgen import generate


def image(tmp_path):
    path = tmp_path / 'sheet.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=11, height=7, count=3,
                       dtype='uint8', transform=from_origin(100, 100, 1, 1)) as ds:
        ds.write(np.zeros((3, 7, 11), dtype='uint8'))
    return path


def test_whole_image_and_no_overwrite(tmp_path):
    p = image(tmp_path); before = p.read_bytes()
    result = generate(tmp_path, p.name, 'whole')
    assert result['jobs'] == ['whole']
    job = json.loads((tmp_path/'whole.json').read_text())
    assert job['area']['geometry']['coordinates'][0] == [[0,0],[11,0],[11,7],[0,7],[0,0]]
    assert job['images'] == [{'path':'sheet.tif'}]
    with pytest.raises(ValueError): generate(tmp_path, p.name, 'whole')
    assert p.read_bytes() == before


def test_uneven_grid_covers_pixels_once_and_conflict_is_atomic(tmp_path):
    p=image(tmp_path)
    result=generate(tmp_path,p.name,'grid',3,2)
    coverage=np.zeros((7,11), dtype=int)
    for name in result['jobs']:
        job=json.loads((tmp_path/f'{name}.json').read_text())
        ring=job['area']['geometry']['coordinates'][0]
        x0,y0=ring[0];x1,y1=ring[2];coverage[y0:y1,x0:x1]+=1
    assert np.all(coverage==1)
    (tmp_path/'blocked-R2C2.json').write_text('preserve')
    with pytest.raises(ValueError): generate(tmp_path,p.name,'blocked',3,2)
    assert not (tmp_path/'blocked-R1C1.json').exists()
    assert (tmp_path/'blocked-R2C2.json').read_text()=='preserve'


@pytest.mark.parametrize('columns,rows',[(0,1),(-1,2),(12,1),(1,8)])
def test_bad_grid(tmp_path,columns,rows):
    p=image(tmp_path)
    with pytest.raises(ValueError): generate(tmp_path,p.name,'invalid',columns,rows)
    assert not list(tmp_path.glob('*.json'))

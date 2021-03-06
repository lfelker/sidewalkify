import geopandas as gpd
import pandas as pd
from shapely import geometry
import logging


def draw_sidewalks(paths, crs={'init': 'epsg:4326'}, resolution=1):
    logging.basicConfig(filename='./output/warnings.log', level=logging.WARNING)

    geometries = []
    side_codes = []
    row_ids = []
    for path in paths:
        for edge in path['edges']:
            offset = edge['offset']
            if offset > 0:
                geom = edge['geometry'].parallel_offset(offset, 'right',
                                                        resolution=resolution,
                                                        join_style=1)
                # FIXME: For some reason, geometry seems to be drawn in reverse
                # order, resulting in counter-clockwise sidewalks. This is
                # unintuitive (as the paths were created clockwise), so we
                # reverse them here. Figure out why this happened!

                # parallel_offset can produce a lot of weird output. We want to keep only correct linestrings
                side_code = edge['forward']
                side = "right" if side_code == 1 else "left"
                row_id = edge['id']
                edge['sidewalk'] = None
                if geom == None:
                    logging.warning("Draw error: sidewalk on " + side + " side of street id " +  str(row_id) + " did not create a geometry")
                elif geom.geom_type == 'MultiLineString':
                    logging.warning("Draw error: sidewalk on " + side + " side of street id " +  str(row_id) + " created a complex geometry that was removed from output")
                elif geom.geom_type == 'LineString' and len(geom.coords) < 2:
                    logging.warning("Draw error: sidewalk on " + side + " side of street id " +  str(row_id) + " created an invalid linestring geometry that was removed from output")
                elif geom.geom_type == 'Point':
                    logging.warning("Draw error: sidewalk on " + side + " side of street id " +  str(row_id) + " created a point geometry that was removed from output")
                else: # valid geometry
                    geom = geometry.LineString(reversed(geom.coords))
                    edge['sidewalk'] = geom
            else:
                edge['sidewalk'] = None

        for i in range(len(path['edges']) - 1):
            edge1 = path['edges'][i]
            edge2 = path['edges'][i + 1]
            geom1, geom2 = trim(edge1, edge2)
            path['edges'][i]['sidewalk'] = geom1
            path['edges'][i + 1]['sidewalk'] = geom2

        if path['cyclic']:
            # Have to check the last-first geoms, too
            edge1 = path['edges'][-1]
            edge2 = path['edges'][0]
            geom1, geom2 = trim(edge1, edge2)
            path['edges'][-1]['sidewalk'] = geom1
            path['edges'][0]['sidewalk'] = geom2


        for edge in path['edges']:
            if edge['sidewalk'] is not None:
                geometries.append(edge['sidewalk'])
                side_codes.append(edge['forward'])
                row_ids.append(edge['id'])

    data = {
        'st_id': row_ids,
        'side': side_codes
    }

    df = pd.DataFrame(data)

    gdf = gpd.GeoDataFrame(df, geometry=geometries)
    gdf.crs = crs

    return gdf


def split(line, point):
    distance_on_line = line.project(point)
    coords = list(line.coords)
    for i, p in enumerate(coords):
        pd = line.project(geometry.Point(p))
        if pd == distance_on_line:
            return [
                geometry.LineString(coords[:i+1]),
                geometry.LineString(coords[i:])
            ]
        elif distance_on_line < pd:
            cp = line.interpolate(distance_on_line)
            ls1_coords = coords[:i]
            ls1_coords.append(cp.coords[0])
            ls2_coords = [cp.coords[0]]
            ls2_coords.extend(coords[i:])
            return [geometry.LineString(ls1_coords),
                    geometry.LineString(ls2_coords)]


def trim(edge1, edge2):
    geom1 = edge1['sidewalk']
    geom2 = edge2['sidewalk']
    if geom1 is None:
        if geom2 is None:
            return (geom1, geom2)
        else:
            # Intersect with 'fake' geom1
            # TODO: see if there's a simple mathy way to do this - avoid
            # drawing offset
            street = edge1['geometry']
            g1 = street.parallel_offset(7, 'right', resolution=10,
                                        join_style=2)
            ixn = g1.intersection(geom2)
            if ixn.is_empty:
                # They don't intersect - skip
                return (geom1, geom2)
            else:
                if ixn.type != 'Point':
                    # Is probably GeometryCollection
                    ixn = ixn[0]
                # They do intersect - trim back geom2
                dist = geom2.project(ixn)
                point = geom2.interpolate(dist)
                geom2 = split(geom2, point)[1]
                return (geom1, geom2)
    else:
        if geom2 is None:
            # Intersect geom1 with 'fake' geom2
            street = edge2['geometry']
            g2 = street.parallel_offset(7, 'right',
                                        resolution=10, join_style=2)
            ixn = g2.intersection(geom1)
            if ixn.is_empty:
                # They don't intersect - skip
                return (geom1, geom2)
            else:
                if ixn.type != 'Point':
                    ixn = ixn[0]
                # They do intersect - trim back geom1
                dist = geom1.project(ixn)
                point = geom1.interpolate(dist)
                geom1 = split(geom1, point)[0]
                return (geom1, geom2)
        else:
            # Both exist - intersect them
            ixn = geom1.intersection(geom2)
            if ixn.is_empty:
                # They don't intersect - make them touch end-to-end
                x1, y1 = geom1.coords[-1]
                x2, y2 = geom2.coords[0]
                avg = ((x1 + x2) / 2, (y1 + y2) / 2)

                geom1 = geometry.LineString(geom1.coords[:-1] + [avg])
                geom2 = geometry.LineString([avg] + geom2.coords[1:])
                return (geom1, geom2)

            if ixn.type != 'Point':
                # Multiple intersections (likely GeometryCollection)
                ixn = ixn[0]
            # Trim back both
            geom1 = split(geom1, ixn)[0]
            geom2 = split(geom2, ixn)[1]

            return (geom1, geom2)

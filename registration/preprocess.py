from pyvistaqt import BackgroundPlotter
import pyvista as pv
import numpy as np
import pyacvd
from pymeshfix import _meshfix
import matplotlib.pyplot as plt
from sklearn.neighbors import NearestNeighbors

class PreProcess:
    def __init__(self, file_name):
        self.file_name = file_name.split('/')[-1].split('.')[0]
        self.file_ext = '.' + file_name.split('/')[-1].split('.')[1]
        self.pvmesh = pv.read(file_name)

        d = np.zeros_like(self.pvmesh.points)
        self.array_name = 'coordinates'
        self.pvmesh[self.array_name] = d[:, 1]
        self.pvmesh.points += d

    @staticmethod
    def repairsample(meshpath, n_vertices=50000, repair = False):
        m = pv.read(meshpath)
        clus = pyacvd.Clustering(m)
        clus.subdivide(3)
        clus.cluster(n_vertices)
        remesh = clus.create_mesh()
        remesh.save('test.ply')
        # remesh_path = meshpath.split('.')[0]+'_r1.stl'
        # remesh.save(remesh_path)
        # if repair == True:
        #     repair_path = meshpath.split('.')[0]+'_r2.stl'
        #     _meshfix.clean_from_file(remesh_path, repair_path)


if __name__ == '__main__':

    data_mesh = "/home/tareq/PycharmProjects/pythonProject/pycranium/data/C.stl"

    # PreProcess.repairsample(data_mesh, 1000, True)


    m = pv.read(data_mesh)
    clus = pyacvd.Clustering(m)
    clus.subdivide(3)
    clus.cluster(500)
    remesh = clus.create_mesh()
    remesh.save('test.stl')
    f = pv.read('test.stl')
    _meshfix.clean_from_file('test.stl', 'test2.stl')
    f2 = pv.read('test2.stl')
    plotter = BackgroundPlotter()
    plotter.add_mesh(f2)


    # plotter2 = BackgroundPlotter()
    # plotter2.add_mesh(pv.read(data_mesh_r1), show_edges=True)

    # plotter3 = BackgroundPlotter()
    # plotter3.add_mesh(pv.read(data_mesh_r2), show_edges=True)




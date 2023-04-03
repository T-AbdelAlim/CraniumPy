import numpy as np
import open3d as o3d
import copy
import pyvista as pv

from icp import icp, draw_registration_result
from nricp import nonrigidIcp
from write_ply import write_ply_file_NICP


def nricp_to_template(templatepath, meshpath, deformedpath='deformed_mesh.ply'):
    # read source file
    sourcemesh = o3d.io.read_triangle_mesh(templatepath)
    targetmesh = o3d.io.read_triangle_mesh(meshpath)
    sourcemesh.compute_vertex_normals()
    targetmesh.compute_vertex_normals()

    # first find rigid registration
    # guess for inital transform for icp
    initial_guess = np.eye(4)
    affine_transform = icp(sourcemesh, targetmesh, initial_guess)

    # creating a new mesh for non rigid transform estimation
    refined_sourcemesh = copy.deepcopy(sourcemesh)
    refined_sourcemesh.transform(affine_transform)
    refined_sourcemesh.compute_vertex_normals()

    # non rigid registration
    deformed_mesh = nonrigidIcp(refined_sourcemesh, targetmesh)

    sourcemesh.paint_uniform_color([0.1, 0.9, 0.1])
    targetmesh.paint_uniform_color([0.9, 0.1, 0.1])
    deformed_mesh.paint_uniform_color([0.1, 0.1, 0.9])
    o3d.visualization.draw_geometries([targetmesh, deformed_mesh])
    o3d.io.write_triangle_mesh(deformedpath, mesh=deformed_mesh)

    # convert deformed mesh as reconstructed output (ply file)

    template = pv.read(templatepath)
    mesh = pv.read(deformedpath)
    write_ply_file_NICP(template, mesh.points, deformedpath)

if __name__ == "__main__":
    template = 'Persona 6.ply'
    mesh = 'pt_trig.ply'
    nricp_to_template(templatepath=template, meshpath=mesh)


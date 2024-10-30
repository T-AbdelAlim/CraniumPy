
import pyvista as pv
import open3d as o3d
from nicp.icp import *
from nicp.nricp import nonrigidIcp
from nicp.write_ply import write_ply_file_NICP
from pathlib import Path

def nricp_to_template(sourcepath, targetpath, icp=True):

    targetpath = Path(targetpath)
    if targetpath.__str__().endswith('_nicp.ply'):
        deformedpath = targetpath
    else:
        deformedpath = targetpath.with_name(targetpath.stem + '_nicp.ply')
    print(deformedpath)

    # Load the source and target meshes
    sourcemesh = pv.read(sourcepath)  # the moving mesh
    targetmesh = pv.read(targetpath)  # the fixed mesh

    # Convert PyVista mesh to Open3D mesh
    def convert_to_open3d(mesh_pv):
        mesh_o3d = o3d.geometry.TriangleMesh()
        mesh_o3d.vertices = o3d.utility.Vector3dVector(mesh_pv.points)
        mesh_o3d.triangles = o3d.utility.Vector3iVector(mesh_pv.faces.reshape(-1, 4)[:, 1:])
        return mesh_o3d

    if icp == True:
        # Perform rigid ICP
        P = np.rollaxis(sourcemesh.points, 1)
        X = np.rollaxis(targetmesh.points, 1)
        Rr, tr, num_iter = IterativeClosestPoint(source_pts=P, target_pts=X, tau=10e-6)
        Np = ApplyTransformation(P, Rr, tr)
        Np = np.rollaxis(Np, 1)

        write_ply_file_NICP(sourcemesh, Np, deformedpath)
        deformed_pv = pv.read(deformedpath)
    else:
        deformed_pv = pv.read(deformedpath)

    # # Convert the rigidly deformed mesh to Open3D format
    deformed_rigid_o3d = convert_to_open3d(deformed_pv)  # source / template
    target_o3d = convert_to_open3d(targetmesh)  # patient
    deformed_mesh = nonrigidIcp(deformed_rigid_o3d, target_o3d)
    o3d.io.write_triangle_mesh(filename=str(deformedpath), mesh=deformed_mesh)

    print('Non-Rigid ICP completed')



if __name__ == "__main__":
    T = r'C:\Users\Tareq\Documents\EMC\data_3d\Patient_analysis\p6_template_RS.ply'
    m1 = r'C:\Users\Tareq\Documents\EMC\data_3d\Derma\Derma2021\2139856\analysis\2139856_20240220_DER.000188_rgF_clipped2.ply'
    m2 = r'C:\Users\Tareq\Documents\EMC\data_3d\Derma\Derma2021\2139856\analysis\2139856_20240521_DER.000029_rgF_clipped2.ply'
    sourcepath = r'C:\Users\Tareq\Documents\EMC\data_3d\Patient_analysis\derma_1964658\analysis\1964658_20231030_DER_MM_chin.ply'
    targetpath = r'C:\Users\Tareq\Documents\EMC\data_3d\Patient_analysis\derma_1964658\analysis\1964658_20240226_DER_MM_chin.ply'

    nricp_to_template(sourcepath=sourcepath, targetpath=targetpath)
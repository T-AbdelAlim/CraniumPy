import pyacvd
from pyvistaqt import BackgroundPlotter
import pyvista as pv
import numpy as np
import matplotlib.pyplot as plt
from sklearn.neighbors import NearestNeighbors

from pymeshfix import _meshfix

class CoordinatePicking:
    def __init__(self, file_name):
        self.file_name = file_name.split('/')[-1].split('.')[0]
        self.file_ext = '.' + file_name.split('/')[-1].split('.')[1]
        self.pvmesh = pv.read(file_name)

        d = np.zeros_like(self.pvmesh.points)
        self.array_name = 'coordinates'
        self.pvmesh[self.array_name] = d[:, 1]
        self.pvmesh.points += d

    def callback(self, mesh, pid, **dargs):
        point = self.pvmesh.points[pid]
        label = ['Index: {}\n{}: {}'.format(pid,
                                            self.array_name,
                                            mesh.points[pid])]
        self.coord = mesh.points[pid]


    def picking(self, plotter, target=None):
        plotter.enable_point_picking(callback=self.callback, show_message=False,
                                    color='red', point_size=20,
                                    use_mesh=True, show_point=True, render_points_as_spheres=True)


        if target == 'nose':
            self.nose_coord = plotter.picked_point
            plotter.add_points(self.nose_coord,
                               render_points_as_spheres=True,
                               point_size=20, color='green')
            plotter.add_text('nasion: {}'.format(str(self.nose_coord)), 'upper_right', font_size=10)
            return self.nose_coord

        elif target == 'left':
            self.left_coord = plotter.picked_point
            plotter.add_points(self.left_coord,
                               render_points_as_spheres=True,
                               point_size=20, color='green')
            plotter.add_text('\nLH tragus: {}'.format(str(self.left_coord)), 'upper_right', font_size=10)
            return self.left_coord

        elif target == 'right':
            self.right_coord = plotter.picked_point
            plotter.add_points(self.right_coord,
                               render_points_as_spheres=True,
                               point_size=20, color='green')
            plotter.add_text('\n\nRH tragus: {}'.format(str(self.right_coord)), 'upper_right', font_size=10)
            return self.right_coord

        else:
            pass

    def centroid(self, xyz):
        x_mean = (xyz[0][0] + xyz[1][0] + xyz[2][0]) / 3
        y_mean = (xyz[0][1] + xyz[1][1] + xyz[2][1]) / 3
        z_mean = (xyz[0][2] + xyz[1][2] + xyz[2][2]) / 3
        centroid = np.array([x_mean, y_mean, z_mean])

        return centroid

    def reg_to_template(self, landmarks):
        # calculate rotations
        def calc_normal_vector(Q, R, S):
            QR = R - Q
            QS = S - Q
            n = np.cross(QR, QS)
            return n

        def angle_between(v1, v2):
            """ Returns the angle in degrees between vectors 'v1' and 'v2'::
            """
            v1_u = v1 / np.linalg.norm(v1)  # unit vector
            v2_u = v2 / np.linalg.norm(v2)
            angle_rad = np.arccos(np.clip(np.dot(v1_u, v2_u), -1.0, 1.0))
            angle_degr = angle_rad * (180 / np.pi)
            return angle_degr

        # landmarks[0] = nasion, [1] = left tragus and [2] = right tragus
        templ_triangle = np.array([[1.00000000e-10, 5.72706234e+01, -2.75124192e-01],
                                   [-6.10000000e+01, -2.86353117e+01, 1.37562096e-01],
                                   [6.10000000e+01, -2.86353117e+01, 1.37562096e-01]])

        templ_surface = pv.PolyData(templ_triangle).delaunay_2d()
        templ_centroid = templ_surface.center_of_mass()

        #calculate translation (centroid to centroid)
        landmark_vertices = np.array(landmarks)

        # avg_trag_x = np.abs(landmarks[1][0]) + np.abs(landmarks[2][0])/2
        self.lm_surf = pv.PolyData(landmark_vertices).delaunay_2d() #landmark surface

        # translation
        self.translation = templ_centroid - np.array(self.lm_surf.center_of_mass())
        self.lm_surf.translate(self.translation)

        # z rotation
        nasion_centroid_templ = np.array(templ_triangle[0]) - np.array(templ_centroid)
        nasion_centroid_mesh = np.array(self.lm_surf.points[0]) - np.array(self.lm_surf.center_of_mass())

        if self.lm_surf.points[2][1] > templ_surface.points[2][1]: #rh tragus higher in y = - rotation_z (cw - topview)
            self.z_rotation = -1 * angle_between(nasion_centroid_mesh, nasion_centroid_templ)
        else:
            self.z_rotation = angle_between(nasion_centroid_mesh, nasion_centroid_templ)
        self.lm_surf.rotate_z(self.z_rotation)

        # y rotation
        if self.lm_surf.points[2][2] > templ_surface.points[2][2]: #rh tragus higher in z = + rotation_y (ccw - frontview)
            self.y_rotation = angle_between(self.lm_surf.face_normals[0], templ_surface.face_normals[0])
        else:
            self.y_rotation = -1 * angle_between(self.lm_surf.face_normals[0], templ_surface.face_normals[0])
        self.lm_surf.rotate_y(self.y_rotation)

        # x rotation
        if self.lm_surf.points[0][2] > templ_surface.points[0][2]: # nasion above = -rotation_x (cw - view rh tragus)
            self.x_rotation = -1 * angle_between(self.lm_surf.face_normals[0], templ_surface.face_normals[0])
        else:
            self.x_rotation = angle_between(self.lm_surf.face_normals[0], templ_surface.face_normals[0])
        self.lm_surf.rotate_x(self.x_rotation)

        return self.translation, self.z_rotation, self.y_rotation, self.x_rotation, self.lm_surf

        # reset coords
        self.nose_coord = self.left_coord = self.right_coord = []


if __name__ == '__main__':
    #% functions
    def angle_between(v1, v2):
        """ Returns the angle in degrees between vectors 'v1' and 'v2'::
        """
        v1_u = v1 / np.linalg.norm(v1)  # unit vector
        v2_u = v2 / np.linalg.norm(v2)
        angle_rad = np.arccos(np.clip(np.dot(v1_u, v2_u), -1.0, 1.0))
        angle_degr = angle_rad * (180 / np.pi)
        return angle_degr

    #% DATA
    plotter = BackgroundPlotter()
    template_mesh = pv.read("/home/tareq/Notebooks_AAT/EMC_research/pycranium/data/template/origin_template_ntplane.stl")
    raw_mesh = CoordinatePicking("/home/tareq/Notebooks_AAT/EMC_research/ICV_CT_correlation/registered_grade_5/dataset/196-22022010/100223132826/100223132826.stl")
    data_mesh = CoordinatePicking("/home/tareq/Notebooks_AAT/EMC_research/ICV_CT_correlation/registered_grade_5/dataset/196-22022010/100223132826/100223132826_H_AAT2.stl")
    # template_triangle = np.array([[1E-10, 56, 12], [-61, -28, -6], [61, -28, -6]]) # not aligned on Nasion-tragus plane
    # (requires rotation around x of -12,37362513427)
    template_triangle = np.array([[ 1.00000000e-10,  5.72706234e+01, -2.75124192e-01],
                                  [-6.10000000e+01, -2.86353117e+01,  1.37562096e-01],
                                  [ 6.10000000e+01, -2.86353117e+01,  1.37562096e-01]])

#####

    # landmarks corresponding to A.stl
    landmarks = np.array([[71.07735443, 38.32688904, 77.00601196], [ 50.20030594,  51.92822266, -15.58328247], [-19.85119438,  12.4160614 ,  67.62042236]])

#####
    #%% VISUALIZE
    plotter.add_points(template_triangle, color='blue', point_size=20, render_points_as_spheres=True)
    # plotter.add_points(template_centroid, color='yellow', point_size=20, render_points_as_spheres=True)
    plotter.add_mesh(template_mesh, color='white', show_edges =True, opacity=0.2)

    # plotter.add_points(landmarks, color='green', point_size=20, render_points_as_spheres=True)
    # plotter.add_points(mesh_centroid, color='black', point_size=20, render_points_as_spheres=True)
    plotter.add_mesh(data_mesh.pvmesh, color='yellow', show_edges=True, opacity=0.6)


## press P (metrics picking = activated)
    # data_mesh.picking(plotter)
    # data_mesh.picking(plotter, 'nose')
    # data_mesh.picking(plotter, 'left')
    # data_mesh.picking(plotter, 'right')

    # plotter.show_grid()

    # cloud1 = pv.PolyData(landmarks)
    # surf1 = cloud1.delaunay_2d()
    # mesh_centroid = surf1.center_of_mass()
    # plotter.add_mesh(surf1, color = 'blue', opacity=0.5)
    #
    # cloud2 = pv.PolyData(template_triangle)
    # surf2 = cloud2.delaunay_2d()
    # template_centroid = surf2.center_of_mass()
    # plotter.add_mesh(surf2, color = 'red', opacity=0.15)

    # data_mesh.reg_to_template(landmarks)
    # t = data_mesh.translation
    # zr = data_mesh.z_rotation
    # yr = data_mesh.y_rotation
    # xr = data_mesh.x_rotation
    #
    # surf1.translate(t)
    # surf1.rotate_z(zr)
    # surf1.rotate_y(yr)
    # surf1.rotate_x(xr)
    #
    # data_mesh.pvmesh.translate(t)
    # data_mesh.pvmesh.rotate_z(zr)
    # data_mesh.pvmesh.rotate_y(yr)
    # data_mesh.pvmesh.rotate_x(xr)
    #
    # for i in range(3):
    #     data_mesh.reg_to_template(surf1.points)
    #     t = data_mesh.translation
    #     zr = data_mesh.z_rotation
    #     yr = data_mesh.y_rotation
    #     xr = data_mesh.x_rotation
    #
    #     surf1.translate(t)
    #     surf1.rotate_z(zr)
    #     surf1.rotate_y(yr)
    #     surf1.rotate_x(xr)
    #
    #     data_mesh.pvmesh.translate(t)
    #     data_mesh.pvmesh.rotate_z(zr)
    #     data_mesh.pvmesh.rotate_y(yr)
    #     data_mesh.pvmesh.rotate_x(xr)

    # surf1.translate(t)
    # surf1.rotate_z(zr)
    # surf1.rotate_y(yr)
    # surf1.rotate_x(-xr)


    # # ### template ###
    # clipped_templ = template_mesh.clip(normal=[0, 0, 1], origin=[0, 0, template_triangle[0][2]], invert=False)
    # plotter.add_mesh(clipped_templ, color='red', opacity=0.1)
    #
    # AX_templ = clipped_templ.slice(normal=[0, 0, 1], origin=[0, 0, 0])
    # COR_templ = clipped_templ.slice(normal=[0, 1, 0], origin=[0, 0, 0])
    # SAG_templ = clipped_templ.slice(normal=[1, 0, 0], origin=[0, 0, 0])
    #
    # plotter.add_mesh(AX_templ, color = 'red')
    # plotter.add_points(AX_templ.center_of_mass(), color = 'red', point_size = 20, render_points_as_spheres=True)
    # plotter.add_mesh(COR_templ, color = 'red')
    # plotter.add_points(COR_templ.center_of_mass(), color = 'red', point_size = 20, render_points_as_spheres=True)
    # plotter.add_mesh(SAG_templ, color = 'red')
    # plotter.add_points(SAG_templ.center_of_mass(), color = 'red', point_size = 20, render_points_as_spheres=True)
    #
    # # #### mesh ####
    # # clipped along nasion-tragus plane
    # clipped_mesh = data_mesh.pvmesh.clip(normal=[0, 0, 1], origin=[0, 0, template_triangle[0][2]], invert=False)
    #
    # AX_slice = clipped_mesh.slice(normal=[0, 0, 1], origin=[0, 0, 0])
    # COR_slice = clipped_mesh.slice(normal=[0, 1, 0], origin=[0, 0, 0])
    # SAG_slice = clipped_mesh.slice(normal=[1, 0, 0], origin=[0, 0, 0])
    #
    # plotter.add_mesh(clipped_mesh, color='blue', opacity=0.1)
    # plotter.add_mesh(AX_slice, color = 'blue')
    # plotter.add_points(AX_slice.center_of_mass(), color = 'blue', point_size = 20, render_points_as_spheres=True)
    # plotter.add_mesh(COR_slice, color = 'blue')
    # plotter.add_points(COR_slice.center_of_mass(), color = 'blue', point_size = 20, render_points_as_spheres=True)
    # plotter.add_mesh(SAG_slice, color = 'blue')
    # plotter.add_points(SAG_slice.center_of_mass(), color = 'blue', point_size = 20, render_points_as_spheres=True)
    #
    # # # Center of Mass correction (0.5*difference between the two CoMs)
    # corrected_mesh = data_mesh.pvmesh.clip(normal=[0, 0, 1], origin=[0, 0, template_triangle[0][2]], invert=False)
    # AX_diff = abs(AX_slice.center_of_mass()[1]-AX_templ.center_of_mass()[1])/2
    # corrected_mesh.translate([0, AX_diff, 0])
    # plotter.add_mesh(corrected_mesh, color='yellow', opacity=0.1)
    #
    # AX_slice_cor = corrected_mesh.slice(normal=[0, 0, 1], origin=[0, 0, 0])
    # COR_slice_cor = corrected_mesh.slice(normal=[0, 1, 0], origin=[0, 0, 0])
    # SAG_slice_cor = corrected_mesh.slice(normal=[1, 0, 0], origin=[0, 0, 0])
    #
    # plotter.add_mesh(AX_slice_cor, color = 'yellow')
    # plotter.add_points(AX_slice_cor.center_of_mass(), color = 'yellow', point_size = 20, render_points_as_spheres=True)
    # plotter.add_mesh(COR_slice_cor, color = 'yellow')
    # plotter.add_points(COR_slice_cor.center_of_mass(), color = 'yellow', point_size = 20, render_points_as_spheres=True)
    # plotter.add_mesh(SAG_slice_cor, color = 'yellow')
    # plotter.add_points(SAG_slice_cor.center_of_mass(), color = 'yellow', point_size = 20, render_points_as_spheres=True)


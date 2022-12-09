"""
Created on Mon Aug 2, 2021
@author: TAbdelAlim
"""

import pyvista as pv
import numpy as np


class CoordinatePicking:
    def __init__(self, file_path):
        self.file_name = file_path.stem
        self.file_ext = file_path.suffix
        self.pvmesh = pv.read(file_path)

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
            plotter.add_text('nasion: {}'.format(str(np.round(self.nose_coord, 1))), 'upper_right', font_size=10)
            return self.nose_coord

        elif target == 'left':
            self.left_coord = plotter.picked_point
            plotter.add_points(self.left_coord,
                               render_points_as_spheres=True,
                               point_size=20, color='green')
            plotter.add_text('\nLH tragus: {}'.format(str(np.round(self.left_coord, 1))), 'upper_right', font_size=10)
            return self.left_coord

        elif target == 'right':
            self.right_coord = plotter.picked_point
            plotter.add_points(self.right_coord,
                               render_points_as_spheres=True,
                               point_size=20, color='green')
            plotter.add_text('\n\nRH tragus: {}'.format(str(np.round(self.right_coord, 1))), 'upper_right',
                             font_size=10)
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

        # calculate translation (centroid to centroid)
        landmark_vertices = np.array(landmarks)

        # avg_trag_x = np.abs(landmarks[1][0]) + np.abs(landmarks[2][0])/2
        self.lm_surf = pv.PolyData(landmark_vertices).delaunay_2d()  # landmark surface

        # translation
        self.translation = templ_centroid - np.array(self.lm_surf.center_of_mass())
        self.lm_surf.translate(self.translation)

        # z rotation
        nasion_centroid_templ = np.array(templ_triangle[0]) - np.array(templ_centroid)
        nasion_centroid_mesh = np.array(self.lm_surf.points[0]) - np.array(self.lm_surf.center_of_mass())

        if self.lm_surf.points[2][1] > templ_surface.points[2][
            1]:  # rh tragus higher in y = - rotation_z (cw - topview)
            self.z_rotation = -1 * angle_between(nasion_centroid_mesh, nasion_centroid_templ)
        else:
            self.z_rotation = angle_between(nasion_centroid_mesh, nasion_centroid_templ)
        self.lm_surf.rotate_z(self.z_rotation)

        # y rotation
        if self.lm_surf.points[2][2] > templ_surface.points[2][
            2]:  # rh tragus higher in z = + rotation_y (ccw - frontview)
            self.y_rotation = angle_between(self.lm_surf.face_normals[0], templ_surface.face_normals[0])
        else:
            self.y_rotation = -1 * angle_between(self.lm_surf.face_normals[0], templ_surface.face_normals[0])
        self.lm_surf.rotate_y(self.y_rotation)

        # x rotation
        if self.lm_surf.points[0][2] > templ_surface.points[0][2]:  # nasion above = -rotation_x (cw - view rh tragus)
            self.x_rotation = -1 * angle_between(self.lm_surf.face_normals[0], templ_surface.face_normals[0])
        else:
            self.x_rotation = angle_between(self.lm_surf.face_normals[0], templ_surface.face_normals[0])
        self.lm_surf.rotate_x(self.x_rotation)

        return self.translation, self.z_rotation, self.y_rotation, self.x_rotation, self.lm_surf

        # reset coords
        self.nose_coord = self.left_coord = self.right_coord = []

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

        self.translation = None
        self.z_rotation = None
        self.y_rotation = None
        self.x_rotation = None
        self.lm_surf = None

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
            plotter.add_text('nasion: {}]'.format(str(np.round(self.nose_coord, 2))), 'upper_right', font_size=10)
            return self.nose_coord

        elif target == 'left':
            self.left_coord = plotter.picked_point
            plotter.add_points(self.left_coord,
                               render_points_as_spheres=True,
                               point_size=20, color='green')
            plotter.add_text('\nLH tragus: {}'.format(str(np.round(self.left_coord, 2))), 'upper_right', font_size=10)
            return self.left_coord

        elif target == 'right':
            self.right_coord = plotter.picked_point
            plotter.add_points(self.right_coord,
                               render_points_as_spheres=True,
                               point_size=20, color='green')
            plotter.add_text('\n\nRH tragus: {}'.format(str(np.round(self.right_coord, 2))), 'upper_right',
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

    @staticmethod
    def calc_normal_vector(Q, R, S):
        QR = R - Q
        QS = S - Q
        n = np.cross(QR, QS)
        return n

    @staticmethod
    def angle_between(v1, v2):
        v1_u = v1 / np.linalg.norm(v1)
        v2_u = v2 / np.linalg.norm(v2)
        angle_rad = np.arccos(np.clip(np.dot(v1_u, v2_u), -1.0, 1.0))
        angle_degr = angle_rad * (180 / np.pi)
        return angle_degr


    def reg_to_template(self, landmarks):

        # calculate rotations
        def calc_normal_vector(Q, R, S):
            QR = R - Q
            QS = S - Q
            n = np.cross(QR, QS)
            return n

        def compute_normal_vector(coords):
            v1 = coords[1] - coords[0]
            v2 = coords[2] - coords[0]
            normal = np.cross(v1, v2)
            normal /= np.linalg.norm(normal)
            #
            # if normal[1] < 0:
            #     normal = -normal

            return normal


        def angle_between(v1, v2):
            """ Returns the angle in degrees between vectors 'v1' and 'v2'::
            """
            v1_u = v1 / np.linalg.norm(v1)  # unit vector
            v2_u = v2 / np.linalg.norm(v2)
            angle_rad = np.arccos(np.clip(np.dot(v1_u, v2_u), -1.0, 1.0))
            angle_degr = angle_rad * (180 / np.pi)
            return angle_degr

        def euler_angles_from_vectors(v1, v2):
            # Normalize the input vectors
            v1_u = v1 / np.linalg.norm(v1)
            v2_u = v2 / np.linalg.norm(v2)

            # Compute the axis of rotation (cross product of the two vectors)
            rotation_axis = np.cross(v1_u, v2_u)
            rotation_axis /= np.linalg.norm(rotation_axis)

            # Compute the angle between the two vectors (in radians)
            angle_rad = np.arccos(np.clip(np.dot(v1_u, v2_u), -1.0, 1.0))

            # Compute the rotation matrix for aligning v1 to v2
            rotation_matrix = np.eye(3)  # Initialize the rotation matrix as an identity matrix
            K = np.array([[0, -rotation_axis[2], rotation_axis[1]],
                          [rotation_axis[2], 0, -rotation_axis[0]],
                          [-rotation_axis[1], rotation_axis[0], 0]])
            rotation_matrix += np.sin(angle_rad) * K + (1 - np.cos(angle_rad)) * np.dot(K, K)

            # Compute Euler angles (in radians) from the rotation matrix
            sy = np.sqrt(rotation_matrix[0, 0] * rotation_matrix[0, 0] + rotation_matrix[1, 0] * rotation_matrix[1, 0])
            singular = sy < 1e-6

            if not singular:
                x = np.arctan2(rotation_matrix[2, 1], rotation_matrix[2, 2])
                y = np.arctan2(-rotation_matrix[2, 0], sy)
                z = np.arctan2(rotation_matrix[1, 0], rotation_matrix[0, 0])
            else:
                x = np.arctan2(-rotation_matrix[1, 2], rotation_matrix[1, 1])
                y = np.arctan2(-rotation_matrix[2, 0], sy)
                z = 0

            # Convert Euler angles to degrees
            euler_angles = np.array([x, y, z]) * (180 / np.pi)

            return euler_angles


        # landmarks[0] = nasion, [1] = left tragus and [2] = right tragus
        templ_triangle = np.array([[1.00000000e-10, -2.75124192e-01, 5.72706234e+01],
                                   [6.10000000e+01, 1.37562096e-01, -2.86353117e+01],
                                   [-6.10000000e+01, 1.37562096e-01, -2.86353117e+01]])

        templ_surface = pv.PolyData(templ_triangle).delaunay_2d()
        templ_centroid = templ_surface.center_of_mass()

        # calculate translation (centroid to centroid)
        landmark_vertices = np.array(landmarks)

        # avg_trag_x = np.abs(landmarks[1][0]) + np.abs(landmarks[2][0])/2
        self.lm_surf = pv.PolyData(landmark_vertices).delaunay_2d()  # landmark surface

        # translation
        self.translation = templ_centroid - np.array(self.lm_surf.center_of_mass())
        self.lm_surf.translate(self.translation)

        # y rotation nasion aligned
        nasion_centroid_templ = np.array(templ_triangle[0]) - np.array(templ_centroid)
        nasion_centroid_mesh = np.array(self.lm_surf.points[0]) - np.array(self.lm_surf.center_of_mass())

        euler_nasion_angles = euler_angles_from_vectors(nasion_centroid_mesh, nasion_centroid_templ)
        self.x_rotation_nasion = euler_nasion_angles[0]
        self.y_rotation_nasion = euler_nasion_angles[1]
        self.z_rotation_nasion = euler_nasion_angles[2]

        self.lm_surf.rotate_x(self.x_rotation_nasion)
        self.lm_surf.rotate_y(self.y_rotation_nasion)
        self.lm_surf.rotate_z(self.z_rotation_nasion)

        # z rotation
        lm_surf_normal = compute_normal_vector(self.lm_surf.points)
        print('original normal {} '.format(lm_surf_normal))
        templ_normal = compute_normal_vector(templ_surface.points)
        euler_face_normals = euler_angles_from_vectors(lm_surf_normal, templ_normal)
        self.x_rotation_normals = euler_face_normals[0]
        self.y_rotation_normals = euler_face_normals[1]
        self.z_rotation_normals = euler_face_normals[2]

        self.lm_surf.rotate_x(self.x_rotation_normals)
        self.lm_surf.rotate_y(self.y_rotation_normals)
        self.lm_surf.rotate_z(self.z_rotation_normals)

        print('new normal {} '.format(lm_surf_normal))

        return self.translation, euler_nasion_angles, euler_face_normals

        # reset coords
        self.nose_coord = self.left_coord = self.right_coord = []

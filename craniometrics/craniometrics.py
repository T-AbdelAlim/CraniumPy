"""
Created on Mon Aug 2, 2021
@author: TAbdelAlim
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyvista as pv


class CranioMetrics:
    """
    Basic Cranial Measurements class

    :param file_name: String representing the filename
    :param slice_d: Horizontal distance between two consequtive slides
    """

    def __init__(self, file_path, slice_d=1):
        # file_path = Path(file_path)
        self.file_name = file_path.stem
        self.file_ext = file_path.suffix
        self.pvmesh = pv.read(file_path)

        d = np.zeros_like(self.pvmesh.points)
        self.array_name = 'coordinates'
        self.pvmesh[self.array_name] = d[:, 1]
        self.pvmesh.points += d

        self.x_bounds = [
            int(np.ceil(self.pvmesh.bounds[0])),
            int(np.ceil(self.pvmesh.bounds[1]))
        ]

        self.y_bounds = [
            int(np.ceil(self.pvmesh.bounds[2])),
            int(np.ceil(self.pvmesh.bounds[3]))
        ]

        self.z_bounds = [
            int(np.ceil(self.pvmesh.bounds[4])),
            int(np.ceil(self.pvmesh.bounds[5]))
        ]

        self.slice_mesh(slice_d)

    def slice_mesh(self, slice_d):
        """
        generate axial slices throughout the mesh and extract measures from
        slices

        :param slice_d: Horizontal distance between two consequtive slides
        :return: Height and index of the slice where max depth is found and
        breadth <180mm to correct for ears.

        """

        # empty_dataframe for slice bounds
        self.slice_df = pd.DataFrame(columns=[
            'depth',
            'breadth',
            'x_min',
            'x_max',
            'y_min',
            'y_max',
            'z',
        ])

        # create slices and calculate bounds/optima for every slice
        for i in range(0, self.z_bounds[1], slice_d):
            self.slice_d = slice_d
            self.mesh_s = self.pvmesh.slice(normal=[0, 0, 1], origin=[0, 0, i])

            mb = self.mesh_s.bounds
            self.slice_df = self.slice_df.append({
                'depth': np.round(mb[3] - mb[2], 2),
                'breadth': np.round(mb[1] - mb[0], 2),
                'x_min': mb[0],
                'x_max': mb[1],
                'y_min': mb[2],
                'y_max': mb[3],
                'z': int(mb[4]),
            }, ignore_index=True)

        # index and z-height at which max depth is found
        self.slice_index = np.where(self.slice_df['depth']
                                    == self.slice_df.depth.max())[0][0]


        # check if the ears are not in the slice (excessive breadth > 170mm)
        # else go to next slice (max 100 slice searches)
        count_b = 0
        while self.slice_df.breadth.iloc[self.slice_index] >= 180 and count_b <=100:
            count_b += 1
            self.slice_index += self.slice_d
            self.slice_df.breadth.iloc[self.slice_index]

        self.slice_height = self.slice_df.iloc[self.slice_index].z
        self.breadth = self.slice_df.iloc[self.slice_index].breadth

    def show_slices(self, plotter, axis='z'):
        # create slices and calculate bounds/optima for every slice
        if axis == 'x':
            for i in range(self.x_bounds[0], self.x_bounds[1], self.slice_d):
                self.mesh_sx = self.pvmesh.slice(normal=[1, 0, 0], origin=[i, 0, 0])
                plotter.add_mesh(self.mesh_sx, color='white')

        if axis == 'y':
            for i in range(self.y_bounds[0], self.y_bounds[1], self.slice_d):
                self.mesh_sy = self.pvmesh.slice(normal=[0, 1, 0], origin=[0, i, 0])
                plotter.add_mesh(self.mesh_sy, color='white')

        if axis == 'z':
            for i in range(self.z_bounds[0], self.z_bounds[1], self.slice_d):
                self.mesh_s = self.pvmesh.slice(normal=[0, 0, 1], origin=[0, 0, i])
                plotter.add_mesh(self.mesh_s, color='white')

    def extract_dimensions(self, slice_height):
        """
        extract_dimensions(self.slice_height) extracts the basic measures from
        the mesh (depth, breadth, CI, HC).

        :param slice_height: Z-value of the slice at which max depth is found
        (self.slice_height) and at which the measures are extracted
        :return: Cranial depth, breadth, CI, HC, xyz coordinates of bounds
        """

        def cart2pol(x, y):  # cartesian to polar (radians)
            rho = np.sqrt(x ** 2 + y ** 2)
            phi = np.arctan2(y, x)
            return (rho, phi)

        def dist_polar(  # phi in rad
                rho1,
                phi1,
                rho2,
                phi2,
        ):
            dist = np.sqrt(rho1 ** 2 + rho2 ** 2 - 2 * rho1 * rho2
                           * np.cos(phi1 - phi2))
            return dist

        HC_slice = self.pvmesh.slice(normal=[0, 0, 1], origin=[0, 0,
                                                               slice_height])
        HCP = HC_slice.points
        polar = []
        for i in range(len(HCP)):
            polar.append(cart2pol(HCP[i][0], HCP[i][1]))

        self.polar_df = pd.DataFrame(polar, columns=['rho', 'phi'
                                                     ]).sort_values('phi').reset_index(drop=True)

        HC_estimate = 0
        for i in range(len(HCP) - 1):
            p = self.polar_df.iloc[i]  # point
            n_p = self.polar_df.iloc[i + 1]  # next_point

            HC_estimate = HC_estimate + dist_polar(p.rho, p.phi,
                                                   n_p.rho, n_p.phi)
            self.HC = np.round(HC_estimate / 10, 1)

        if self.HC <= 60:
            self.slice_index = np.where(self.slice_df['z']
                                        == slice_height)[0][0]
        else:
            slice_height += self.slice_d
            self.extract_dimensions(slice_height)

        self.HC_s = self.pvmesh.slice(normal=[0, 0, 1], origin=[0, 0,
                                                                self.slice_height])

        hb = self.HC_s.bounds
        self.depth = np.round(hb[3] - hb[2], 2)
        self.breadth = np.round(hb[1] - hb[0], 2)
        self.CI = np.round(100 * (self.breadth / self.depth), 1)

        lh_opt_index = np.where(self.HC_s.points[:, 0] == hb[0])
        self.lh_opt = self.HC_s.points[lh_opt_index][0]

        rh_opt_index = np.where(self.HC_s.points[:, 0] == hb[1])
        self.rh_opt = self.HC_s.points[rh_opt_index][0]

        occ_opt_index = np.where(self.HC_s.points[:, 1] == hb[2])
        self.occ_opt = self.HC_s.points[occ_opt_index][0]

        front_opt_index = np.where(self.HC_s.points[:, 1] == hb[3])
        self.front_opt = self.HC_s.points[front_opt_index][0]

        self.optima_df = pd.DataFrame(columns=['front_opt', 'occ_opt',
                                               'rh_opt', 'lh_opt'])
        self.optima_df = self.optima_df.append({
            'front_opt': self.front_opt,
            'occ_opt': self.occ_opt,
            'rh_opt': self.rh_opt,
            'lh_opt': self.lh_opt,
        }, ignore_index=True)

    def plot_craniometrics(self, plotter):
        """
        plotting of the extracted extracted craniometrics

        :param opacity: Mesh opacity
        :return: pv.BackgroundPlotter containing the extracted measures in text,
        the original mesh and in red: HC line and the four optima used to
        calculated the CI.
        """
        plotter.add_mesh(self.HC_s, color='red', line_width=5)
        plotter.add_points(np.array([self.front_opt, self.occ_opt,
                                     self.lh_opt, self.rh_opt]),
                           render_points_as_spheres=True,
                           point_size=20, color='red')
        plotter.add_text('''file = {}.stl
OFC (depth) = {} mm
BPD (breadth) = {} mm
Cephalic Index = {}
Circumference = {} cm 
Mesh volume. = {} cc '''.format(
            self.file_name,
            round(np.float64(self.depth), 2),
            round(np.float64(self.breadth), 2),
            self.CI,
            self.HC,
            round((self.pvmesh.volume / 1000), 2),
        ), font_size=10, color='white')

# ICV correlation based on CT: round((((self.pvmesh.volume / 1000) + 46.4349) / 1.4566), 2)

    def plot_HC_slice(self):
        self.extract_dimensions(self.slice_height)
        fig = plt.figure()
        ax = fig.add_subplot(111, projection='polar')
        plt.polar(self.polar_df["phi"], self.polar_df["rho"], color='r')  # plot polar HC

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

        self.coord = plotter.picked_point

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
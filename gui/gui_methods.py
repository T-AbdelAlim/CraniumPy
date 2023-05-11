"""
Created on Mon Aug 2, 2021
Last update on May 1, 2023
@author: TAbdelAlim
"""

from tkinter.filedialog import askopenfilename, asksaveasfilename
import datetime
import pyacvd
import pyvista as pv
import numpy as np
from pymeshfix import _meshfix
from pathlib import Path
from craniometrics.craniometrics import CranioMetrics
from registration.picking import CoordinatePicking
from registration.write_ply import write_ply_file
import json
import datetime


import open3d as o3d
from nicp.icp import icp
from nicp.nricp import nonrigidIcp
from nicp.write_ply import write_ply_file_NICP
import copy


class GuiMethods:
    def __init__(self):
        self.mesh_color = 'ivory'
        self.template_color = 'saddlebrown'
        self.template_path = Path('./template/clipped_template_xy.ply')
        self.template_path_cranium = Path('./template/clipped_template_xy_com.ply')
        self.template_path_face = Path('./template/template_face.ply')
        self.template_path_head = Path('./template/template_xy_com.ply') # experimental

        self.CoM_translation = True

    # File tab
    def import_mesh(self, resample=False):
        self.plotter.clear()  # clears mesh space every time a new mesh is added
        self.plotter.view_xy()
        self.file_path = Path(askopenfilename(title="Select file to open",
                                              filetypes=(("Mesh files", ("*.ply", "*.obj", "*.stl")),
                                                         ("all files", "*.*"))))
        try:
            self.file_name = self.file_path.name  # returns name.suffix
            self.extension = self.file_path.suffix
            self.mesh_file = pv.read(self.file_path)
            self.plotter.add_mesh(self.mesh_file, color=self.mesh_color, show_edges=True)

            self.plotter.reset_camera()
            self.plotter.show_grid()
            self.landmarks = [[], [], []]
        except:
            pass

    def clean_mesh(self):
        try:
            self.plotter.clear()
            self.plotter.add_mesh(self.mesh_file, color=self.mesh_color, show_edges=True)
        except:
            pass

    def mesh_edges(self, show=True, opacity=1):
        self.plotter.clear()
        if show == False:
            opacity = 0.8

        self.plotter.add_mesh(self.mesh_file, color=self.mesh_color, show_edges=show, opacity=opacity)

    def resample_repair(self, n_vertices=20000, repair=False):
        resampled_path = self.file_path.with_name(self.file_path.stem + '_rs.ply')  # + self.extension for source ext
        GuiMethods.repairsample(self.file_path, postfix='_rs', n_vertices=n_vertices, repair=repair)
        self.file_path = resampled_path

    @staticmethod
    def call_template(ICV_scaling=1.0, CoM_translation=True, target='cranium'): #target = face/cranium/head
        # if CoM_translation == True:
        #     template_path = Path('./template/clipped_template_xy_com.ply')
        # else:
        #     template_path = Path('./template/clipped_template_xy.ply')

        if target == 'cranium' and CoM_translation == True:
            template_path = Path('./template/clipped_template_xy_com.ply')
        elif target == 'face':
            template_path = Path('./template/template_face.ply')
        elif target == 'head' and CoM_translation == True:
            template_path = Path('./template/template_xy_com.ply')


        template_mesh = pv.read(template_path)
        if target != 'face':
            template_mesh.points *= ICV_scaling ** (1 / 3)  # template_volume = 2339070.752133594

        return template_mesh

    def show_registration(self, target='cranium'):
        self.plotter.clear()

        try:
            template_mesh = GuiMethods.call_template(ICV_scaling=1,
                                                     CoM_translation=self.CoM_translation, target=target)
            self.plotter.add_mesh(template_mesh, color=self.template_color, opacity=0.5, show_edges=True)
            self.plotter.add_mesh(self.mesh_file, color=self.mesh_color, show_edges=False, opacity=0.5)
            self.plotter.add_legend(labels=[['template', self.template_color], ['mesh', self.mesh_color]],
                                    face='circle')


        except:
            template_mesh = GuiMethods.call_template(target=target)

            self.plotter.add_mesh(template_mesh, color=self.template_color, opacity=0.5, show_edges=True)
            self.plotter.add_legend(labels=[['template', self.template_color]], face='circle')
            self.plotter.reset_camera()



    def flip(self):
        self.plotter.clear()

        try:
            self.mesh_file.flip_y(point=[0, 0, 0], transform_all_input_vectors=True)
            self.mesh_file.flip_x(point=[0, 0, 0], transform_all_input_vectors=True)
            suffix = "_rgF" if str(self.file_path).endswith('_rgF.ply') else "_rg"
            self.file_path = GuiMethods.save_ply_file(self.mesh_file, self.file_path, suffix)
            self.mesh_file = pv.read(self.file_path)
            self.plotter.add_mesh(self.mesh_file, color=self.mesh_color, show_edges=True)
            self.plotter.show_grid()
            self.plotter.reset_camera()

        except:
            pass

    @staticmethod
    def three_slices(mesh_file, plotter, color='yellow'):
        AX_slice = mesh_file.slice(normal=[0, 0, 1], origin=[0, 0, 2])
        COR_slice = mesh_file.slice(normal=[0, 1, 0], origin=[0, 0, 2])
        SAG_slice = mesh_file.slice(normal=[1, 0, 0], origin=[0, 0, 2])

        plotter.add_mesh(AX_slice, color=color)
        plotter.add_points(AX_slice.center_of_mass(), color=color, point_size=20, render_points_as_spheres=True)
        plotter.add_mesh(COR_slice, color=color)
        plotter.add_points(COR_slice.center_of_mass(), color=color, point_size=20, render_points_as_spheres=True)
        plotter.add_mesh(SAG_slice, color=color)
        plotter.add_points(SAG_slice.center_of_mass(), color=color, point_size=20, render_points_as_spheres=True)

    @staticmethod
    def repairsample(file_path, n_vertices, postfix='', repair=False, extension=".ply"):
        remesh = pv.read(file_path)

        if remesh.n_points <= 150000:
            clus = pyacvd.Clustering(remesh)
            clus.subdivide(3)
            clus.cluster(n_vertices)
            remesh = clus.create_mesh()

        elif remesh.n_points > 150000:
            print('Mesh contains too many vertices ({}). Mesh is not resampled.'.format(remesh.n_points))

        remesh_path = file_path.with_name(file_path.stem + postfix + extension)
        write_ply_file(remesh, remesh_path)

        if repair == True:
            _meshfix.clean_from_file(str(remesh_path), str(remesh_path))

    @staticmethod
    def save_ply_file(mesh, file_path, suffix):
        stem = file_path.stem
        if not stem.endswith(suffix):
            stem += suffix
        new_file_path = file_path.with_name(stem + ".ply")
        write_ply_file(mesh, str(new_file_path))
        return new_file_path

    # Reg tab
    def coordinate_picking(self, target):
        try:
            metrics = CoordinatePicking(self.file_path)
            metrics.picking(self.plotter, target)
            if target == 'nose':
                self.landmarks[0] = metrics.nose_coord
            elif target == 'left':
                self.landmarks[1] = metrics.left_coord
            elif target == 'right':
                self.landmarks[2] = metrics.right_coord

            if len(self.landmarks[0]) == len(self.landmarks[1]) == len(self.landmarks[2]) == 3:
                return self.landmarks
        except:
            pass

    def register(self, landmarks, n_iterations=10, target='cranium'):
        metrics = CoordinatePicking(self.file_path)

        # first iteration based on selected landmarks
        metrics.reg_to_template(landmarks)
        print("mesh translation {}".format(metrics.translation))
        print("nasion pitching {}".format(metrics.x_rotation_nasion))
        print("nasion rotation {}".format(metrics.y_rotation_nasion))
        print("tragi rotation {}".format(metrics.z_rotation_nasion))

        self.mesh_file.translate(metrics.translation)
        self.mesh_file.rotate_x(metrics.x_rotation_nasion, transform_all_input_vectors=True)
        self.mesh_file.rotate_y(metrics.y_rotation_nasion, transform_all_input_vectors=True)
        self.mesh_file.rotate_z(metrics.z_rotation_nasion, transform_all_input_vectors=True)

        self.mesh_file.rotate_x(metrics.x_rotation_normals, transform_all_input_vectors=True)
        self.mesh_file.rotate_y(metrics.y_rotation_normals, transform_all_input_vectors=True)
        self.mesh_file.rotate_z(metrics.z_rotation_normals, transform_all_input_vectors=True)


        suffix = "_rgF" if target == "face" else "_rg"
        self.file_path = GuiMethods.save_ply_file(self.mesh_file, self.file_path, suffix)

        template_path = Path("./template/template_xy.ply")
        if self.CoM_translation == True:
            # if False: the centroid of the 3 landmarks is used as the origin in the frame of reference.
            # if True: the mesh is translated along the z-axis (front-back) based on the center of mass of the HC slice
            self.com_translation(suffix=suffix)
            template_path = Path("./template/template_xy_com.ply")
            metrics.lm_surf.translate(self.CoM_value)


        if target == 'face':
            template_path = Path("./template/template_face.ply")
            self.mesh_file.translate([-1 * metrics.lm_surf.points[0][0], -1 * metrics.lm_surf.points[0][1],
                                      -1 * metrics.lm_surf.points[0][2]])
            metrics.lm_surf.translate([-1 * metrics.lm_surf.points[0][0], -1 * metrics.lm_surf.points[0][1],
                                       -1 * metrics.lm_surf.points[0][2]])

            self.file_path = GuiMethods.save_ply_file(self.mesh_file, self.file_path, suffix)

        # # replace old with new registered mesh
        self.plotter.clear()  # clears mesh space every time a new mesh is added
        self.file_name = Path(self.file_path).stem
        self.mesh_file = pv.read(self.file_path)
        self.newpos_landmarks = metrics.lm_surf.points

        self.plotter.add_mesh(self.mesh_file, color=self.mesh_color, opacity=0.5, show_edges=True)
        self.plotter.add_points(self.newpos_landmarks, render_points_as_spheres=True, color='green', point_size=20,
                                opacity=0.5)
        self.plotter.reset_camera()

        ## show registration
        GuiMethods.three_slices(self.mesh_file, self.plotter, self.mesh_color)

        template_mesh = pv.read(template_path)

        self.plotter.add_mesh(template_mesh, color=self.template_color, opacity=0.1)
        GuiMethods.three_slices(template_mesh, self.plotter, self.template_color)
        self.plotter.add_legend(labels=[['template', self.template_color], ['mesh', self.mesh_color]], face='circle')

        # Landmarks as json --> Read: t = pd.read_json("filename_landmarks.json", lines=True)
        ## xpos == nasion coordinates, ypos == left tragus coordinates, z_pos == right tragus coordinates
        dictionary = {
            "datetime": str(datetime.datetime.now().strftime("%Y-%m-%d/%H:%M:%S")),
            "CoM": str(self.CoM_translation),
            "initial_nasion": np.round([self.landmarks[0][0], self.landmarks[0][1],
                                        self.landmarks[0][2]], 3).tolist(),
            "initial_lh_coord": np.round([self.landmarks[1][0], self.landmarks[1][1],
                                          self.landmarks[1][2]], 3).tolist(),
            "initial_rh_coord": np.round([self.landmarks[2][0], self.landmarks[2][1],
                                          self.landmarks[2][2]], 3).tolist(),
            "new_nasion": np.round([self.newpos_landmarks[0][0], self.newpos_landmarks[0][1],
                                    self.newpos_landmarks[0][2]], 3).tolist(),
            "new_lh_coord": np.round([self.newpos_landmarks[2][0], self.newpos_landmarks[2][1],
                                      self.newpos_landmarks[2][2]], 3).tolist(),
            "new_rh_coord": np.round([self.newpos_landmarks[1][0], self.newpos_landmarks[1][1],
                                      self.newpos_landmarks[1][2]], 3).tolist()
        }

        jsonpath = str(self.file_path.parent.joinpath(self.file_name + '_landmarks.json'))
        ## uncomment if you wish to append registration to existing .json file instead of overwriting the file.
        # if os.path.exists(jsonpath):
        #     mode = "a"
        # else:
        #     mode = "w+"
        mode = "w+"
        with open(jsonpath, mode) as outfile:
            json.dump(dictionary, outfile)
            outfile.write('\n')

    # Translation
    def com_translation(self, suffix=None):
        temp_metric = CranioMetrics(self.file_path)  # temporary metric of the mesh
        temp_metric.extract_dimensions(temp_metric.slice_height)
        CoM = temp_metric.HC_s.center_of_mass()
        # self.mesh_file.translate([-CoM[0], 0, -CoM[2]]) # uncomment for lateral CoM translation
        self.mesh_file.translate([0, 0, -CoM[2]])
        self.CoM_value = [0, 0, -CoM[2]]
        print('Center of Mass correction: {}'.format(self.CoM_value))

        if suffix != None:
            self.file_path = GuiMethods.save_ply_file(self.mesh_file, self.file_path, suffix)
        else:
            write_ply_file(self.mesh_file, str(self.file_path))

    def cranial_cut(self, initial_clip=False):
        try:
            self.plotter.clear()
            self.plotter.add_text('Mesh processing...\nThis may take a moment.', position='upper_left')
            if initial_clip == True:
                clip = -20
            else:
                clip = 0

            template_mesh = GuiMethods.call_template(ICV_scaling=self.mesh_file.volume / 2339070.752133594)
            template_mesh.points *= 1.2

            self.mesh_file.clip_box(template_mesh.bounds, invert=False)
            self.mesh_file.clip(normal=[0, 0.6, 1], origin=[0, -60, -50], invert=False)
            self.mesh_file = self.mesh_file.clip('y', origin=[0, -21, 0], invert=False)

            if str(self.file_path.stem).endswith('_C'):
                pass
            else:
                self.file_path = self.file_path.with_name(self.file_path.stem + '_C.ply')
            write_ply_file(self.mesh_file, self.file_path)

            GuiMethods.repairsample(self.file_path, n_vertices=20000, repair=True)

            self.mesh_file = pv.read(self.file_path)

            # write_ply_file(self.mesh_file.clip('z', origin=[0, 0, clip], invert=False), self.file_path)
            write_ply_file(self.mesh_file.clip('y', origin=[0, clip, 0], invert=False), self.file_path)

            GuiMethods.repairsample(self.file_path, n_vertices=10000, repair=False)

            self.mesh_file = pv.read(self.file_path)
            self.plotter.clear()
            # self.plotter.add_mesh(self.mesh_file, color=self.mesh_color, show_edges=True)
            write_ply_file(self.mesh_file, self.file_path)

            if self.CoM_translation:
                temp_metric = CranioMetrics(self.file_path)  # temporary metric of the mesh
                temp_metric.extract_dimensions(temp_metric.slice_height)
                CoM = temp_metric.HC_s.center_of_mass()
                self.mesh_file.translate([-CoM[0], 0, -CoM[2]])
                write_ply_file(self.mesh_file, self.file_path)

            self.plotter.add_mesh(self.mesh_file, color=self.mesh_color, show_edges=True)

        except:
            pass

    def facial_clip(self, initial_clip=False):

        try:
            self.plotter.clear()
            self.plotter.add_text('Mesh processing...\nThis may take a moment.', position='upper_left')
            if initial_clip == True:
                clip = -20
            else:
                clip = 0

            template_mesh = GuiMethods.call_template(target='face')

            lmk_surface = pv.PolyData(self.newpos_landmarks).delaunay_2d()
            templ_centroid = lmk_surface.center_of_mass()

            # self.mesh_file.clip_box(template_mesh.bounds, invert=False)
            self.mesh_file = self.mesh_file.clip('z', origin=[0, 20, templ_centroid[2] - 1], invert=False)

            if str(self.file_path.stem).endswith('_CF'):
                pass
            else:
                self.file_path = self.file_path.with_name(self.file_path.stem + '_CF.ply')
            write_ply_file(self.mesh_file, self.file_path)

            GuiMethods.repairsample(self.file_path, n_vertices=20000, repair=True)

            self.mesh_file = pv.read(self.file_path)

            write_ply_file(self.mesh_file.clip('z', origin=[0, 20, templ_centroid[2]], invert=False), self.file_path)

            GuiMethods.repairsample(self.file_path, n_vertices=10000, repair=False)

            self.mesh_file = pv.read(self.file_path)
            self.plotter.clear()
            write_ply_file(self.mesh_file, self.file_path)

            self.plotter.add_mesh(self.mesh_file, color=self.mesh_color, show_edges=True)

        except:
            pass

    # Craniometrics tab
    def craniometrics(self, slice_only=False):
        try:
            if slice_only == True:
                self.plotter.clear()
                self.plotter.show_grid()

            metrics = CranioMetrics(self.file_path)
            metrics.extract_dimensions(metrics.slice_height)
            metrics.plot_craniometrics(self.plotter, n_axes=1,
                                       slice_only=slice_only)  # n_axes = 1 -> only extracts axial slice

            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            measurements = {
                "Datetime": current_time,
                "Filepath": "{}".format(self.file_path),
                "OFD_depth_mm": round(np.float64(metrics.depth), 2),
                "BPD_breadth_mm": round(np.float64(metrics.breadth), 2),
                "Cephalic_Index": metrics.CI,
                "Circumference_cm": metrics.HC,
                "MeshVolume_cc": round((metrics.pvmesh.volume / 1000), 2),
            }

            # Write the measurements to a JSON file
            jsonpath_metrics = str(self.file_path.parent.joinpath(self.file_name + '_metrics.json'))
            print('metricspath {}'.format(jsonpath_metrics))
            with open(jsonpath_metrics, "+w") as jsonpath_metrics:
                json.dump(measurements, jsonpath_metrics, indent=4)


        except:
            pass

    # View tab
    def screenshot(self):
        try:
            screenshot_folder = Path(asksaveasfilename(title="Select file to open",
                                                       filetypes=(("Screenshot", "*.png"),
                                                                  ("all files", "*.*"))))
            self.plotter.screenshot(screenshot_folder)
        except:
            pass

    def nricp_to_template(self, target='cranium'):
        try:
            self.plotter.clear()
            self.plotter.add_text('Non-rigid ICP ({}) in progress...\nThis may take a moment.'.format(target), position='upper_left')
            sourcepath = self.template_path_cranium.__str__()
            if target == 'face':
                sourcepath = self.template_path_face.__str__()
            elif target == 'head':
                sourcepath = self.template_path_head.__str__()

            targetpath = str(self.file_path)
            if str(self.file_path).endswith('_' + target[0] + 'icp.ply'):
                deformedpath = self.file_path
            else:
                deformedpath = self.file_path.with_name(self.file_path.stem + '_' + target[0] + 'icp.ply')
            print(deformedpath)

            # read source file
            sourcemesh = o3d.io.read_triangle_mesh(sourcepath)
            targetmesh = o3d.io.read_triangle_mesh(targetpath)

            sourcemesh.compute_vertex_normals()
            targetmesh.compute_vertex_normals()

            ## Volumetric scaling
            # compute volume ratio between source and target mesh
            target_vol = pv.read(targetpath).volume
            source_vol = pv.read(sourcepath).volume
            volume_ratio = np.power(target_vol / source_vol, 1 / 3)
            print(volume_ratio)

            # scale source mesh to match target mesh volume
            sc=sourcemesh.get_center()

            sourcemesh.scale(volume_ratio, center=[sc[0],0,sc[0]])

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
            o3d.io.write_triangle_mesh(filename=str(deformedpath), mesh=deformed_mesh)

            # convert deformed mesh as reconstructed output (ply file)
            sourcem = pv.read(sourcepath)
            targetm = pv.read(deformedpath)
            write_ply_file_NICP(sourcem, targetm.points, deformedpath)
            print('NICP completed')
            self.file_path = deformedpath
            self.plotter.clear()
            self.mesh_file = pv.read(self.file_path)
            self.plotter.add_mesh(self.mesh_file, show_edges=False)
            self.plotter.add_points(self.mesh_file.points, color = 'k', render_points_as_spheres=True, opacity=0.75)

        except:
            pass
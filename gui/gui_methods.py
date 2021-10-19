import random
from tkinter.filedialog import askopenfilename
import os
import pyacvd
import pyvista as pv
from pymeshfix import _meshfix
from datetime import datetime
from craniometrics.craniometrics import CranioMetrics
from registration.picking import CoordinatePicking
from registration.write_ply import write_ply_file
from pathlib import Path

class GuiMethods:

    # File tab
    def import_mesh(self, resample=False):
        self.plotter.clear()  # clears mesh space every time a new mesh is added
        self.file_path = Path(askopenfilename(title="Select file to open",
                                         filetypes=(("Mesh files", "*.ply"),
                                                    ("all files", "*.*"))))

        self.file_name = self.file_path.name
        self.extension = self.file_path.suffix
        self.mesh_file = pv.read(self.file_path)
        self.show_mesh()

        self.plotter.reset_camera()
        self.plotter.show_grid()
        self.landmarks = [[], [], []]

    def show_mesh(self, edges=True):
        try:
            self.plotter.add_mesh(self.mesh_file, rgba=True, show_edges=edges)
        except:
            self.plotter.add_mesh(self.mesh_file, color='white', show_edges=edges)

    def clean_mesh(self):
        self.plotter.clear()
        self.show_mesh()

    def mesh_edges(self, edges=True):
        self.plotter.clear()
        self.show_mesh(edges=edges)

    # def resample_repair(self, n_vertices=10000, repair=False):
    #     resampled_path = self.file_path.split('.')[0] + '_rs.' + self.extension
    #     GuiMethods.repairsample(self.file_path, postfix='_rs', n_vertices=n_vertices, repair=repair)
    #     self.file_path = resampled_path

    # @staticmethod
    # def call_template(ICV_scaling=1):
    #     template_mesh = pv.read("C:/Users/Tareq/PycharmProjects/PyCraniumWIn/pycranium/data/template/clipped_template_ntplane.stl")
    #     template_mesh.points *= ICV_scaling ** (1 / 3) # template_volume = 2339070.752133594
    #     return template_mesh
    #
    # def show_registration(self):
    #     self.plotter.clear()
    #     template_mesh = GuiMethods.call_template(ICV_scaling=self.mesh_file.volume/2339070.752133594)
    #     self.plotter.add_mesh(template_mesh, color='red', opacity=0.2, show_edges=True)
    #     try:
    #         try:
    #             self.plotter.add_mesh(self.mesh_file, rgba=True, show_edges=True, opacity=1)
    #         except:
    #             self.plotter.add_mesh(self.mesh_file, color='white', show_edges=True, opacity=1)
    #         GuiMethods.three_slices(self.mesh_file, self.plotter, 'yellow')
    #         # template_mesh.points *= (self.mesh_file.volume / template_mesh.volume) ** (1 / 3) # comment if you dont want to resize cranium
    #
    #         # slight longitudinal correction based on center of mass - translation applied to template
    #         CoM_correction = GuiMethods.CoM_correction(self.mesh_file, template_mesh)
    #         print(CoM_correction)
    #         template_mesh.translate([0, -1*CoM_correction, 0])
    #         GuiMethods.three_slices(template_mesh, self.plotter, 'red')
    #
    #     except AttributeError:
    #         GuiMethods.three_slices(template_mesh, self.plotter, 'red')
    #
    #
    # @staticmethod
    # def three_slices(mesh_file, plotter, color='yellow'):
    #     AX_slice = mesh_file.slice(normal=[0, 0, 1], origin=[0, 0, 1])
    #     COR_slice = mesh_file.slice(normal=[0, 1, 0], origin=[0, 0, 1])
    #     SAG_slice = mesh_file.slice(normal=[1, 0, 0], origin=[0, 0, 1])
    #
    #     plotter.add_mesh(AX_slice, color=color)
    #     plotter.add_points(AX_slice.center_of_mass(), color=color, point_size=20, render_points_as_spheres=True)
    #     plotter.add_mesh(COR_slice, color=color)
    #     plotter.add_points(COR_slice.center_of_mass(), color=color, point_size=20, render_points_as_spheres=True)
    #     plotter.add_mesh(SAG_slice, color=color)
    #     plotter.add_points(SAG_slice.center_of_mass(), color=color, point_size=20, render_points_as_spheres=True)
    #
    #
    # @staticmethod
    # def repairsample(file_path, n_vertices, postfix = '', repair=False, extension=".ply"):
    #     clus = pyacvd.Clustering(pv.read(file_path))
    #     clus.subdivide(3)
    #     clus.cluster(n_vertices)
    #     remesh = clus.create_mesh()
    #     remesh_path = file_path.split('.')[0] +postfix + extension
    #     # remesh.save(remesh_path)
    #     write_ply_file(remesh, remesh_path)
    #     ####
    #     # mesh = pv.read(dirpath + '/' + filename)
    #     # arr_facen = mesh.point_normals
    #     # np.savetxt(dirpath + '/' + filename.replace('ply', 'txt'), arr_facen)
    #     # write_ply_file(remesh, 'test.ply')
    #     ####
    #     if repair == True:
    #         _meshfix.clean_from_file(remesh_path, remesh_path)
    #
    # # Reg tab
    # def coordinate_picking(self, target):
    #     metrics = CoordinatePicking(self.file_path)
    #     metrics.picking(self.plotter, target)
    #     if target == 'nose':
    #         self.landmarks[0] = metrics.nose_coord
    #     elif target == 'left':
    #         self.landmarks[1] = metrics.left_coord
    #     elif target == 'right':
    #         self.landmarks[2] = metrics.right_coord
    #
    #     if len(self.landmarks[0]) == len(self.landmarks[1]) == len(self.landmarks[2]) == 3:
    #         return self.landmarks
    #
    # def register(self, landmarks, n_iterations = 50):
    #     metrics = CoordinatePicking(self.file_path)
    #     # first iteration based on selected landmarks
    #     metrics.reg_to_template(landmarks)
    #     self.mesh_file.translate(metrics.translation)
    #     self.mesh_file.rotate_z(metrics.z_rotation)
    #     self.mesh_file.rotate_y(metrics.y_rotation)
    #     self.mesh_file.rotate_x(metrics.x_rotation)
    #
    #     for i in range(n_iterations):
    #         metrics.reg_to_template(metrics.lm_surf.points)
    #         self.mesh_file.translate(metrics.translation)
    #         self.mesh_file.rotate_z(metrics.z_rotation)
    #         self.mesh_file.rotate_y(metrics.y_rotation)
    #         self.mesh_file.rotate_x(metrics.x_rotation)
    #     self.mesh_file.save(self.file_path)
    #
    #     if str(self.file_path).endswith('_rg.'+ self.extension) or str(self.file_path).endswith('_C.'+ self.extension):
    #         self.mesh_file.save(self.file_path)
    #     else:
    #         self.mesh_file.save(self.file_path.split('.')[0] + '_rg.' + self.extension)
    #         self.file_path = self.file_path.split('.')[0] + '_rg.' + self.extension
    #
    #     # replace old with new registered mesh
    #     self.plotter.clear()  # clears mesh space every time a new mesh is added
    #     self.file_name = self.file_path.split("/")[-1]
    #     self.mesh_file = pv.read(self.file_path)
    #     # self.plotter.add_mesh(self.mesh_file, color='yellow', opacity=0.5)
    #     try:
    #         self.plotter.add_mesh(self.mesh_file, rgba=True, opacity=0.5, show_edges=True)
    #     except:
    #         self.plotter.add_mesh(self.mesh_file, color='white', opacity=0.5, show_edges=True)
    #     self.plotter.reset_camera()
    #
    #     # show registration
    #     GuiMethods.three_slices(self.mesh_file, self.plotter, 'yellow')
    #     template_mesh = pv.read("C:/Users/Tareq/PycharmProjects/PyCraniumWIn/pycranium/data/template/origin_template_ntplane.stl")
    #     self.plotter.add_mesh(template_mesh, color='red', opacity=0.1)
    #     GuiMethods.three_slices(template_mesh, self.plotter, 'red')
    #
    #     # write initial landmarks to text
    #     txtpath = "/".join(self.file_path.split("/")[:-1]) + "/landmarks.txt"
    #     if os.path.exists(txtpath):
    #         mode = "a"
    #     else:
    #         mode = "w+"
    #
    #     f = open(txtpath, mode)
    #     f.write(str(self.landmarks)+"\n")
    #     f.close()
    #
    # @staticmethod
    # def CoM_correction(pv_cranium, template_mesh):
    #     # template_mesh = pv.read("./data/template/origin_template_ntplane.stl")
    #     AX_templ = template_mesh.slice(normal=[0, 0, 1], origin=[0, 0, 0.1])
    #     AX_slice = pv_cranium.slice(normal=[0, 0, 1], origin=[0, 0, 0.1])
    #     AX_diff = (AX_templ.center_of_mass()[1] - AX_slice.center_of_mass()[1])# /2
    #
    #     return AX_diff
    #
    #
    # def cranial_cut(self, initial_clip = True):
    #     if initial_clip == True:
    #         clip = -20
    #     else:
    #         clip = 0
    #
    #     template_mesh = GuiMethods.call_template(ICV_scaling=self.mesh_file.volume/2339070.752133594)
    #     template_mesh.points *= 1.2
    #
    #     self.mesh_file.clip_box(template_mesh.bounds, invert=False)
    #     self.mesh_file.clip(normal=[0, 0.6, 1], origin=[0, -50, -60], invert=False)
    #     self.mesh_file = self.mesh_file.clip('z', origin=[0, 0, -20], invert=False)
    #
    #     if str(self.file_path).endswith('_C.' + self.extension):
    #         cranium_path = self.file_path
    #     else:
    #         cranium_path = self.file_path.split('.')[0] + '_C.' + self.extension
    #     self.mesh_file.save(cranium_path)
    #
    #     GuiMethods.repairsample(cranium_path, n_vertices=20000, repair=True)
    #
    #     self.file_path = cranium_path
    #     self.mesh_file = pv.read(self.file_path)
    #     self.mesh_file.clip('z', origin=[0, 0, clip], invert=False).save(self.file_path)
    #
    #     self.mesh_file = pv.read(self.file_path)
    #     # CoM_correction = GuiMethods.CoM_correction(self.mesh_file)
    #
    #     self.plotter.clear()
    #     try:
    #         self.plotter.add_mesh(self.mesh_file, rgba=True, show_edges=True)
    #     except:
    #         self.plotter.add_mesh(self.mesh_file, color='white', show_edges=True)
    #     # self.mesh_file.translate([0, CoM_correction, 0])
    #     self.mesh_file.save(self.file_path)
    #
    #
    # # Craniometrics tab
    # def craniometrics(self):
    #     metrics = CranioMetrics(self.file_path)
    #     metrics.extract_dimensions(metrics.slice_height)
    #     metrics.plot_craniometrics(self.plotter)
    #
    # # Dev tab
    # def show_z_slices(self):
    #     CranioMetrics(self.file_path).show_slices(self.plotter, axis='z')
    #
    # def show_x_slices(self):
    #     CranioMetrics(self.file_path).show_slices(self.plotter, axis='x')
    #
    # def show_y_slices(self):
    #     CranioMetrics(self.file_path).show_slices(self.plotter, axis='y')
    #
    # def ins_mesh(self):
    #     try:
    #         self.plotter.add_mesh(self.mesh_file, rgba=True, show_edges=True)
    #     except:
    #         self.plotter.add_mesh(self.mesh_file, color='white', show_edges=True)
    #
    # def screenshot(self):
    #     self.plotter.clear()
    #     self.plotter.background_color = 'white'
    #     try:
    #         self.plotter.add_mesh(self.mesh_file, rgba=True, show_edges=True)
    #     except:
    #         self.plotter.add_mesh(self.mesh_file, color='white', show_edges=True)
    #     screenshot_folder = self.file_path.replace(self.file_path.suffix,'.png')
    #     try:
    #         self.plotter.screenshot(screenshot_folder + self.file_name+'.png')
    #     except AttributeError:
    #         self.plotter.screenshot(
    #             screenshot_folder + str(datetime.now().time()) + '.png')
    #     self.plotter.background_color = 'darkgrey'
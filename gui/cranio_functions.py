# Add this to main script to import:
# from craniometrics.craniometrics import CranioMetrics


### Buttons:

# extract measurements
meshMenu = mainMenu.addMenu('Craniometrics')
self.measurements_action = Qt.QAction('Extract measures', self)
self.measurements_action.triggered.connect(self.craniometrics)
meshMenu.addAction(self.measurements_action)



### Functions:
## Extract measurements
# def craniometrics(self):
#     file_name = self.file_path.split("/")[-1]
#     metrics = CranioMetrics(self.file_path)
#     metrics.extract_dimensions(metrics.slice_height)
#     self.plotter.add_mesh(metrics.HC_s, color='red')
#     self.plotter.add_points(np.array([metrics.front_opt, metrics.occ_opt,
#                                       metrics.lh_opt, metrics.rh_opt]),
#                             render_points_as_spheres=True,
#                             point_size=20, color='red')
#     self.plotter.add_text(
#         '''
#         mesh file: {}
#         slice distance: {} mm
#         depth = {} mm
#         breadth = {} mm
#         CI = {}
#         HC = {} cm'''.format(
#             file_name,
#             metrics.slice_d,
#             round(np.float64(metrics.depth), 2),
#             round(np.float64(metrics.breadth), 2),
#             metrics.CI,
#             metrics.HC,
#         ), font_size=10)
#
#     self.plotterR.add_mesh(metrics.HC_s, color='red')
#     self.plotterR.add_points(np.array([metrics.front_opt, metrics.occ_opt,
#                                        metrics.lh_opt, metrics.rh_opt]),
#                              render_points_as_spheres=True,
#                              point_size=20, color='red')
#
# # camera functions
# def xy_camera(self, var):
#     self.plotter.view_xy()
#
# def xz_camera(self, var):
#     self.plotter.view_xz()
#
# def xz_n_camera(self, var):
#     self.plotter.view_xz(True)
#
# def yz_camera(self, var):
#     self.plotter.view_yz()
#
# def yz_n_camera(self, var):
#     self.plotter.view_yz(True)
#
# def reset_camera(self, var):
#     self.plotter.isometric_view()
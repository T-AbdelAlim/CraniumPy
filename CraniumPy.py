"""
Created on Mon Aug 2, 2021
@author: T-AbdelAlim
"""

import sys
from PyQt5 import Qt, QtCore
from tkinter import Tk
from pyvistaqt import QtInteractor
from gui.gui_methods import GuiMethods


class MainWindow(Qt.QMainWindow, GuiMethods):

    def __init__(self, parent=None, show=True):
        '''
        Initialize gui window (without buttons)
        '''
        Qt.QMainWindow.__init__(self, parent)

        # create the frame
        self.frame = Qt.QFrame()
        hlayout = Qt.QHBoxLayout()

        # set the title
        self.setWindowTitle("CraniumPy")
        # add the pyvista interactor object
        self.plotter = QtInteractor(self.frame)
        self.plotter.add_axes()
        self.plotter.view_xz(-1)
        hlayout.addWidget(self.plotter.interactor)

        self.frame.setLayout(hlayout)
        self.setCentralWidget(self.frame)

    def buttons(self):
        '''
        Add buttons to initialized window

        Create new menu:
        newMenu = mainMenu.addMenu('new menu')

        Adding a new button:
        newButton = Qt.QAction('new button', self): create new action button
        newButton.setShortcut('Ctrl+N'): set shortcut if desired
        newButton.triggered.connect(method): add method that should be triggered when pressing new button
        newMenu.addAction(newButton): add new button to new menu
        '''

        # Basic menubar
        mainMenu = self.menuBar()
        fileMenu = mainMenu.addMenu('File')
        regMenu = mainMenu.addMenu('Registration')
        metricsMenu = mainMenu.addMenu('Cranium')
        # trigMenu = mainMenu.addMenu('Frontal bone')
        viewMenu = mainMenu.addMenu('View')

        # mainMenu - Import mesh button
        importButton = Qt.QAction('Import mesh (.ply)', self)
        importButton.setShortcut('Ctrl+I')
        importButton.triggered.connect(self.import_mesh)
        fileMenu.addAction(importButton)


        # mainMenu - Exit button
        exitButton = Qt.QAction('Exit', self)
        exitButton.setShortcut('Ctrl+Q')
        exitButton.triggered.connect(self.close)
        fileMenu.addAction(exitButton)

        ## REGISTRATION
        pickMenu = regMenu.addMenu('(1) Landmark selection')
        # regMenu - CPD Registration button
        pickButton = Qt.QAction('Enable picking (press P)', self)
        pickButton.setShortcut('Ctrl+P')
        pickButton.triggered.connect(lambda: self.coordinate_picking(target=None))
        pickMenu.addAction(pickButton)

        # regMenu - coordinate 1 (nose)
        save_c1_Button = Qt.QAction('Save coordinate 1 (nasion)', self)
        save_c1_Button.setShortcut('Ctrl+N')
        save_c1_Button.triggered.connect(lambda: self.coordinate_picking(target='nose'))
        pickMenu.addAction(save_c1_Button)

        # regMenu - coordinate 2 (left)
        save_c2_Button = Qt.QAction('Save coordinate 2 (LH side)', self)
        save_c2_Button.setShortcut('Ctrl+L')
        save_c2_Button.triggered.connect(lambda: self.coordinate_picking(target='left'))
        pickMenu.addAction(save_c2_Button)

        # regMenu - coordinate 3 (right)
        save_c3_Button = Qt.QAction('Save coordinate 3 (RH side)', self)
        save_c3_Button.setShortcut('Ctrl+R')
        save_c3_Button.triggered.connect(lambda: self.coordinate_picking(target='right'))
        pickMenu.addAction(save_c3_Button)

        # regMenu - register
        reg_Button = Qt.QAction('(2) Register to template', self)
        reg_Button.triggered.connect(lambda: self.register(self.landmarks, CoM_translation=True))
        regMenu.addAction(reg_Button)

        # regMenu - Clip Mesh
        FclipButton = Qt.QAction('(3) Clip, Repair, Resample', self)
        FclipButton.triggered.connect(lambda: self.cranial_cut(initial_clip=False))
        regMenu.addAction(FclipButton)

        ## metricsMenu - show registration wrt cranial template
        templButton = Qt.QAction('(4) Show registration', self)
        templButton.triggered.connect(self.show_registration)
        regMenu.addAction(templButton)



        ## CRANIOMETRICS (cranium)
        # metricsMenu - extract measurements button
        extractButton = Qt.QAction('Extract measurements', self)
        extractButton.setShortcut('Ctrl+E')
        extractButton.triggered.connect(self.craniometrics)
        metricsMenu.addAction(extractButton)

        # metricsMenu - extract slice only
        sliceextractButton = Qt.QAction('Show 2D slice', self)
        sliceextractButton.triggered.connect(lambda: self.craniometrics(slice_only=True))
        metricsMenu.addAction(sliceextractButton)

        # metricsMenu - extract mesh button
        cleanmeshButton = Qt.QAction('Re-load mesh', self)
        cleanmeshButton.triggered.connect(self.clean_mesh)
        metricsMenu.addAction(cleanmeshButton)

        # ## VIEW
        viewsMenu = viewMenu.addMenu('Camera View')
        xyButton = Qt.QAction('XY-plane (top)', self)
        xyButton.triggered.connect(lambda: self.plotter.view_xy())
        viewsMenu.addAction(xyButton)

        xzinvButton = Qt.QAction('XZ-plane (front)', self)
        xzinvButton.triggered.connect(lambda: self.plotter.view_xz(True))
        viewsMenu.addAction(xzinvButton)

        xzButton = Qt.QAction('XZ-plane (rear)', self)
        xzButton.triggered.connect(lambda: self.plotter.view_xz())
        viewsMenu.addAction(xzButton)

        yzinvButton = Qt.QAction('YZ-plane (left)', self)
        yzinvButton.triggered.connect(lambda: self.plotter.view_yz(True))
        viewsMenu.addAction(yzinvButton)

        yzButton = Qt.QAction('YZ-plane (right)', self)
        yzButton.triggered.connect(lambda: self.plotter.view_yz())
        viewsMenu.addAction(yzButton)

        resetviewButton = Qt.QAction('Reset camera', self)
        resetviewButton.triggered.connect(lambda: self.plotter.isometric_view())
        viewsMenu.addAction(resetviewButton)

        # ## VIEW
        gridMenu = viewMenu.addMenu('Measurement grid')
        sgridButton = Qt.QAction('Show grid', self)
        sgridButton.triggered.connect(lambda: self.plotter.show_grid(grid=True))
        gridMenu.addAction(sgridButton)

        hgridButton = Qt.QAction('Hide grid', self)
        hgridButton.triggered.connect(lambda: self.plotter.show_grid(grid=False,  show_xaxis=False, show_yaxis=False,
                                                                     show_zaxis=False))
        gridMenu.addAction(hgridButton)

        # ## viewsMenu - Screenshot
        ssButton = Qt.QAction('Screenshot', self)
        ssButton.setShortcut('Ctrl+S')
        ssButton.triggered.connect(self.screenshot)
        viewMenu.addAction(ssButton)


if __name__ == '__main__':
    print('Running CraniumPy 0.2.3')
    root = Tk()
    root.withdraw()  #removes tkwindow from file import
    app = Qt.QApplication(sys.argv)
    window = MainWindow()
    window.buttons()
    window.show()
    sys.exit(app.exec_())


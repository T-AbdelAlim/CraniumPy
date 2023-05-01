"""
Created on Mon Aug 2, 2021
Last update on May 1, 2023
@author: T-AbdelAlim
"""

import sys
from PyQt5 import Qt, QtCore
from tkinter import Tk
from pyvistaqt import QtInteractor
from gui.gui_methods import GuiMethods
from PyQt5.QtGui import QPixmap, QFont, QIcon
from PyQt5.QtWidgets import QLabel


class WelcomeScreen(Qt.QDialog):
    def __init__(self, parent=None):
        super(WelcomeScreen, self).__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.Qt.WindowContextHelpButtonHint)
        self.setWindowIcon(QIcon("resources/CraniumPy_logo.ico"))
        self.setWindowTitle("Welcome to CraniumPy")

        layout = Qt.QVBoxLayout()

        # Add custom figure
        self.add_custom_figure("resources/welcomeCP.jpg", layout)

        # Add button
        start_button = Qt.QPushButton("CraniumPy v0.4.0")
        font = QFont("Arial", 14)  # Change font to Arial with a size of 12
        start_button.setFont(font)
        try:
            start_button.setStyleSheet("font-family: 'Arial Nova Light'; font-size: 14; color: rgb(0, 35, 40);")
        except:
            pass
        start_button.clicked.connect(self.accept)  # Close the welcome screen when the button is clicked
        layout.addWidget(start_button)

        self.setLayout(layout)

    def add_custom_figure(self, image_path, layout):
        pixmap = QPixmap(image_path)
        image_label = QLabel()
        image_label.setPixmap(pixmap)
        image_label.setScaledContents(True)  # This will enable the image to scale with the window size
        layout.addWidget(image_label)


class MainWindow(Qt.QMainWindow, GuiMethods):

    def __init__(self, parent=None, show=True):
        '''
        Initialize gui window (without buttons)
        '''
        Qt.QMainWindow.__init__(self, parent)
        self.setWindowIcon(QIcon("resources/CraniumPy_logo.ico"))
        self.resize(1000, 1000)

        # create the frame
        self.frame = Qt.QFrame()
        hlayout = Qt.QHBoxLayout()

        # set the title
        self.setWindowTitle("CraniumPy")
        # add the pyvista interactor object
        self.plotter = QtInteractor(self.frame)
        self.plotter.add_axes()
        self.plotter.view_xy()
        hlayout.addWidget(self.plotter.interactor)

        self.frame.setLayout(hlayout)
        self.setCentralWidget(self.frame)

        self.coordinate_picking(target=None)

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
        regMenu = mainMenu.addMenu('Global alignment')
        nicpMenu = mainMenu.addMenu('Correspondence')
        metricsMenu = mainMenu.addMenu('Cephalometry')
        viewMenu = mainMenu.addMenu('View')

        # mainMenu - Import mesh button
        importButton = Qt.QAction('Import mesh (.ply)', self)
        importButton.triggered.connect(self.import_mesh)
        importButton.triggered.connect(lambda: self.coordinate_picking(target=None))
        fileMenu.addAction(importButton)

        # mainMenu - Exit button
        exitButton = Qt.QAction('Exit', self)
        exitButton.triggered.connect(self.close)
        fileMenu.addAction(exitButton)

        ## FIDUCIAL
        pickMenu = regMenu.addMenu('(1) Landmark selection (press P)')

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
        regoptMenu = regMenu.addMenu('(2) Register for ')
        regH_Button = Qt.QAction('Cranial analysis', self)
        regH_Button.triggered.connect(lambda: self.register(self.landmarks, target='cranium'))
        regoptMenu.addAction(regH_Button)

        # regMenu - register
        regF_Button = Qt.QAction('Facial analysis', self)
        regF_Button.triggered.connect(lambda: self.register(self.landmarks, target='face'))
        regoptMenu.addAction(regF_Button)

        # regMenu - Clip Mesh
        clipMenu = regMenu.addMenu('(3) Clip, Repair, Resample')
        FclipButton = Qt.QAction('Cranium', self)
        FclipButton.triggered.connect(lambda: self.cranial_cut(initial_clip=False))
        clipMenu.addAction(FclipButton)

        # regMenu - Clip Mesh
        FclipButton2 = Qt.QAction('Face', self)
        FclipButton2.triggered.connect(lambda: self.facial_clip(initial_clip=False))
        clipMenu.addAction(FclipButton2)

        ## metricsMenu - show registration wrt cranial template
        showMenu = regMenu.addMenu('(4) Show registration')
        templButton = Qt.QAction('Cranium', self)
        templButton.triggered.connect(self.show_registration)
        showMenu.addAction(templButton)

        ## metricsMenu - show registration wrt cranial template
        templButton2 = Qt.QAction('Face', self)
        templButton2.triggered.connect(self.show_registration_face)
        showMenu.addAction(templButton2)


        ## NICP
        pickMenu2 = nicpMenu.addMenu('NICP cranium')
        pickButton2 = Qt.QAction('Show target', self)
        pickButton2.triggered.connect(self.show_registration)
        pickMenu2.addAction(pickButton2)

        reg_Button2 = Qt.QAction('Calculate', self)
        reg_Button2.triggered.connect(lambda: self.nricp_to_template(target='cranium'))
        pickMenu2.addAction(reg_Button2)

        pickMenu3 = nicpMenu.addMenu('NICP face')
        pickButton3 = Qt.QAction('Show target', self)
        pickButton3.triggered.connect(self.show_registration_face)
        pickMenu3.addAction(pickButton3)

        reg_Button3 = Qt.QAction('Calculate', self)
        reg_Button3.triggered.connect(lambda: self.nricp_to_template(target='face'))
        pickMenu3.addAction(reg_Button3)

        pickMenu4 = nicpMenu.addMenu('Experimental')
        reg_Button4 = Qt.QAction('NICP head', self)
        reg_Button4.triggered.connect(lambda: self.nricp_to_template(target='head'))
        pickMenu4.addAction(reg_Button4)


        ## CRANIOMETRICS (cranium)
        # metricsMenu - extract measurements button
        extractButton = Qt.QAction('Extract measurements', self)
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
        xyButton = Qt.QAction(' XY plane (front)', self)
        xyButton.triggered.connect(lambda: self.plotter.view_xy())
        viewsMenu.addAction(xyButton)

        xzinvButton = Qt.QAction('-XZ plane (top)', self)
        xzinvButton.triggered.connect(lambda: self.plotter.view_xz(True))
        viewsMenu.addAction(xzinvButton)

        xzButton = Qt.QAction('-XY plane (rear)', self)
        xzButton.triggered.connect(lambda: self.plotter.view_xy(True))
        viewsMenu.addAction(xzButton)

        yzButton = Qt.QAction(' ZY plane (right)', self)
        yzButton.triggered.connect(lambda: self.plotter.view_zy())
        viewsMenu.addAction(yzButton)

        yzinvButton = Qt.QAction('-ZY plane (left)', self)
        yzinvButton.triggered.connect(lambda: self.plotter.view_zy(True))
        viewsMenu.addAction(yzinvButton)

        resetviewButton = Qt.QAction(' XZ plane (bottom)', self)
        resetviewButton.triggered.connect(lambda: self.plotter.view_xz())
        viewsMenu.addAction(resetviewButton)

        # ## VIEW
        gridMenu = viewMenu.addMenu('Measurement grid')
        sgridButton = Qt.QAction('Show grid', self)
        sgridButton.triggered.connect(lambda: self.plotter.show_grid(grid=True))
        gridMenu.addAction(sgridButton)

        hgridButton = Qt.QAction('Hide grid', self)
        hgridButton.triggered.connect(lambda: self.plotter.show_grid(grid=False, show_xaxis=False, show_yaxis=False,
                                                                     show_zaxis=False))
        gridMenu.addAction(hgridButton)

        # ## viewsMenu - Screenshot
        ssButton = Qt.QAction('Screenshot', self)
        ssButton.setShortcut('Ctrl+S')
        ssButton.triggered.connect(self.screenshot)
        viewMenu.addAction(ssButton)


if __name__ == '__main__':
    print('Running CraniumPy 0.4.0')
    root = Tk()
    root.withdraw()  # removes tkwindow from file import
    app = Qt.QApplication(sys.argv)

    # Show the welcome screen
    welcome_screen = WelcomeScreen()
    if welcome_screen.exec() == Qt.QDialog.Accepted:
        window = MainWindow()
        window.buttons()
        window.show()
        sys.exit(app.exec_())
    else:
        sys.exit(0)
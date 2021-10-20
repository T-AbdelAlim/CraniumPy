# CraniumPy
CraniumPy is a simple tool that can be used to register 3D meshes for cranial analysis. In its current state, a raw 3D mesh (.ply, .obj, .stl) can be imported and visualized. Three anatomical landmarks were carefully selected (Nasion, LH tragus, RH tragus) and used for registration based on an average normal template (https://dined3d.io.tudelft.nl/en/mannequin/tool). 
Based on a single transverse slice (at max head depth), cephalometric measurements are automatically extracted and plotted on the 3D model. These measurements include:
- head depth
- breadth
- cephalic index
- head circumference
- intracranial volume approximation

![Reconstruction](resources/CraniumPy_info.png)


## Installation and usage
Project is created with:
* Python version: 3.8

To run this project:
1. Create and/or load a virtual environment (optional):
```
conda create -n yourenvname python=3.8
conda activate yourenvname
```
2. Clone repository:
```
git clone https://github.com/T-AbdelAlim/CraniumPy.git
cd CraniumPy
```
4. Install requirements:
```
pip install -r requirements.txt
```

5. Run tool:
```
Python main.py
```

5. To get started check out the documentation in  ```/resources/documentation.pdf```

## CraniumPy as an executable
If you want to run this tool locally from an executable file:

1. Install pyinstaller:
```
pip install pyinstaller
```

2. From the CraniumPy main directory run:
```
pyinstaller main.py --hidden-import vtkmodules --hidden-import vtkmodules.all --hidden-import vtkmodules.util.numpy_support --hidden-import vtkmodules.numpy_interface --hidden-import vtkmodules.numpy_interface.dataset_adapter --hidden-import vtkmodules.qt --hidden-import vttmodules.util --hidden-import vttmodules.vtkCommonCore --hidden-import vttmodules.vtkCommonKitPython --hidden-import vtkmodules.qt.QVTKRenderWindowInteractor  --onefile --clean
```

3. Move the executable file (main.exe) from ```CraniumPy/dist/main.exe``` to the main directory ```CraniumPy/dist/main.exe```
4. Run main.exe (takes a few seconds to start)

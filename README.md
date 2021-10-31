# CraniumPy
[![DOI](https://zenodo.org/badge/418914708.svg)](https://zenodo.org/badge/latestdoi/418914708)

CraniumPy is a simple tool that can be used to register 3D meshes for cranial analysis using three landmarks. In its current state, a raw 3D mesh (.ply, .obj, .stl) can be imported and visualized. After registration, cephalometric measurements can be automatically extracted. These measurements include:
- head depth
- head breadth
- cephalic index
- head circumference
- intracranial volume approximation

![Reconstruction](resources/CraniumPy_info.png)

## Contents
  * [Usage](#usage)
  * [Installation](#installation)
  * [CraniumPy executebale](#craniumpy-executebale)
  * [Citation](#citation)
  * [Author](#author)

## Usage
Three anatomical landmarks  selected (Nasion, LH tragus, RH tragus) that need to be located by the user for registration. The mesh is then registered to an average normal template (https://dined3d.io.tudelft.nl/en/mannequin/tool). 

Based on a single transverse slice (at maximum head depth), cephalometric measurements are automatically extracted and plotted on the 3D model. 

Check the [step-by-step guide](/resources/documentation.pdf) to get started.

The example mesh ```resources/test_mesh/test_mesh.ply``` can be used to explore the functionality of this tool. 

## Installation
Project is created with:
* Python version: 3.8

To run this project:
1. Create and/or load a virtual environment (optional):

```
conda create -n yourenvname python=3.8
conda activate yourenvname
```
If you are unfamiliar with virtual environments, check [miniconda](https://docs.conda.io/en/latest/miniconda.html).

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

## CraniumPy executebale
If you want to run this tool locally (on Windows) from an executable file (.exe):

1. Install pyinstaller:
```
pip install pyinstaller
```

2. From the CraniumPy main directory run:
```
pyinstaller main.py --hidden-import vtkmodules --hidden-import vtkmodules.all --hidden-import vtkmodules.util.numpy_support --hidden-import vtkmodules.numpy_interface --hidden-import vtkmodules.numpy_interface.dataset_adapter --hidden-import vtkmodules.qt --hidden-import vttmodules.util --hidden-import vttmodules.vtkCommonCore --hidden-import vttmodules.vtkCommonKitPython --hidden-import vtkmodules.qt.QVTKRenderWindowInteractor  --onefile --clean
```

3. Move the executable file (main.exe) from ```CraniumPy/dist/main.exe``` to the main directory ```CraniumPy/main.exe``` and run main.exe from here (takes a few seconds to start)


## Citation
If you use CraniumPy, please cite:

Abdel-Alim, T. (2021). CraniumPy [Computer software]. https://doi.org/10.5281/zenodo.5634154
## Author
Tareq Abdel-Alim (Department of Neurosurgery and Radiology, Erasmus MC, Rotterdam, the Netherlands)

If you have any questions, suggestions, or problems do not hesitate to contact me:
t.abdelalim@erasmusmc.nl

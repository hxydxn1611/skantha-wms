import os
import sys

def install_roboflow():
    try:
        import roboflow
        print("Roboflow package is already installed.")
    except ImportError:
        print("Installing roboflow package...")
        os.system(f"{sys.executable} -m pip install roboflow")

def download_dataset(api_key, workspace_name, project_name, version_num=1):
    from roboflow import Roboflow
    print(f"Connecting to Roboflow workspace '{workspace_name}'...")
    rf = Roboflow(api_key=api_key)
    project = rf.workspace(workspace_name).project(project_name)
    version = project.version(version_num)
    
    print("Downloading dataset in Ultralytics YOLO format (for YOLO11)...")
    # This will download the dataset and return the dataset object
    dataset = version.download("yolo11")
    
    print(f"\n✅ Dataset downloaded successfully to: {dataset.location}")
    print(f"The YOLO data.yaml is located at: {dataset.location}/data.yaml")
    
    # Generate the training command
    print("\n=============================================")
    print("🔥 READY TO TRAIN 🔥")
    print("=============================================")
    print("You can now fine-tune your model by running:")
    print(f"py train.py --data {dataset.location}/data.yaml --epochs 50")
    print("=============================================\n")

if __name__ == "__main__":
    install_roboflow()
    print("\n===========================================================")
    print("Roboflow Dataset Integrator")
    print("===========================================================")
    print("You can find these details on your Roboflow dataset page")
    print("under 'Export' -> 'Format: YOLO11' -> 'Get Snippet'.")
    print("===========================================================\n")
    
    api_key = input("Enter your Roboflow API Key: ").strip()
    workspace = input("Enter your Workspace name: ").strip()
    project = input("Enter your Project name: ").strip()
    version = input("Enter the dataset version number (default 1): ").strip()
    
    if not version:
        version = 1
    else:
        version = int(version)
        
    download_dataset(api_key, workspace, project, version)

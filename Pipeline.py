################################################################################
# Author:  Joy Roy, William Reynolds, Rafael Ceschin
# Purpose: The following is a pipeline made by PIRC at UPMC CHP in order to
#          preprocess BOLD fMRIs and to use those outputs for similarity 
#          matrix generation.
#
# This pipeline is currently being editted to more closely fit Power et al 2012
#
# Contact: jor115@pitt.edu
# Acknowledgments: Ansh Patel from The Hillman Academy contributed to this work.
################################################################################

################################################################################
##TO DO: 
# 1. Allow configuration of data/output/workingdir location
# 2. Allow configuration of template/segmentation files
# 3. Allow configuration of verbosity
# 4. Allow configuration of intermediate product storage
# 5. Take a config file to change paramters
# 6. (Optional) Take inline arguments from terminal
# 7. (Optional) Print blurb at beginning and end of the pipeline things users
#     should be aware of
##
################################################################################

import nibabel as nib
import nipy as nipy
import nipype.algorithms.rapidart as rpd    # rapidart module
import nipype.interfaces.io as nio          # Data i/o
import nipype.interfaces.fsl as fsl         # fsl
import nipype.interfaces.ants as ants       # ANTs
import nipype.interfaces.utility as util    # utility
import nipype.pipeline.engine as pe         # pypeline engine
import numpy as np
import os, sys


# ******************************************************************************
# ARGUMENTS AND CONFIGURATIONS
# ******************************************************************************

isTest = True

#sets the directories that will be used in the pipeline 
home_dir = os.getcwd()
data_dir = '/data' #the directory where the data is located
template_path = '/app/Template/MNI152lin_T1_2mm_brain.nii.gz' #the path where the template is located
segment_path = '/app/Template/AAL3v1_CombinedThalami_444.nii.gz'#template where thalami regions combined #added by joy
scheduleTXT = '/app/Template/sched.txt'
#############TEMPORARY FOR TESTING####################
if isTest==True:
    data_dir = '/Users/joy/Desktop/Research/funconnect2/preprocessing/sample_data'
    template_path = '/Users/joy/Desktop/Research/funconnect2/docker/Template/MNI152lin_T1_4mm_brain.nii.gz'
    segment_path = '/Users/joy/Desktop/Research/funconnect2/docker/Template/AAL3v1_CombinedThalami_444.nii.gz'
    scheduleTXT = '/Users/joy/Desktop/Research/funconnect2/docker/Template/sched.txt'
#############TEMPORARY FOR TESTING####################
# The pipeline graph and workflow directory will be outputted here
os.chdir(home_dir) #sets the directory of the workspace to the location of the data
# Sets default output to a compressed NIFTI
fsl.FSLCommand.set_default_output_type('NIFTI_GZ') #sets the default output type to .nii.gz
# NOTE: These lines control where the output is sorted.
# The derivatives folder should be a directory outside of the subjects directory
# This helps allows us to keep inputs and outputs in seperate locations.
# It is named 'derivatives' in accordance to BIDS (although this pipeline does
# not assume BIDS input YET)
derivatives_dir = os.path.join(data_dir, 'derivatives')
# Leave this blank if you do not want an extra directory of outputs
# We suggest you keep it incase youre running mulitple pipelines 
# together on the same input files. This will differentiate pipeline outputs
# Suggested names: 'FunkyConnect' or 'FunkyBrainSpawn' or 'JoyIsCool'
OUTFOLDERNAME = 'output'
# NOTE: THIS ALLOWS FOR ALL INTERMEDIATE OUTPUTS TO BE SAVED
SAVE_INTERMEDIATES = True
# NOTE: This is necessary to keep track of the original template range
MAX_SEGMENT_VAL = int(nib.load(segment_path).get_fdata().max())
MAX_SEGMENT_VAL = 170
# NOTE: The following looks for Niftis in the data dir 
# This does not include any niftis in the output directory
subject_list_abs = []
for dirpath, dirnames, filenames in os.walk(data_dir):
    for filename in [f for f in filenames if '.nii' in f]:
        if (derivatives_dir in dirpath) or ('derivatives' in dirpath):
            continue
        else:
            filepath = os.path.join(dirpath, filename)
            subject_list_abs.append(filepath)
subject_list_abs = sorted(subject_list_abs)
# print(subject_list_abs)

# ******************************************************************************
# HELPER FUNCTIONS
# ******************************************************************************

#Note: outputs the home directory of the data to output all results to
def GenerateOutDir(base_outputdir, image_path):
    import os
    subj = image_path.split('/')[-3]
    sess = image_path.split('/')[-2]
    out_dir = os.path.join(base_outputdir, subj, sess)
    os.makedirs(out_dir, exist_ok = True)

    return out_dir


# Note: collects the TR value from the image and calculates the sigma value for bandpass filtering
def calculate_sigma(image_path, hp_frequency=0.009, lp_frequency=0.08):
    import nibabel as nib
    func_img = nib.load(image_path)
    header = func_img.header
    test_tuple=header.get_zooms()
    sigma_val_hp = 1 / ((test_tuple[-1]) * hp_frequency)
    sigma_val_lp = 1 / ((test_tuple[-1]) * lp_frequency)
    return sigma_val_hp, sigma_val_lp


# Note: This function helps to determine the best volume to use as a reference for motion correction.
def findBestReference(in_file, scheduleTXT, derivatives_dir):
    import nibabel as nib
    import numpy as np
    from tqdm import tqdm
    import os, sys
    import json
    sys.path.append('/data/')
    import pipeline_functions as pf

    entryname = '/'.join(in_file.split('/')[-3:])
    file_name = "best_frames.json"
    # Check if the file exists in the directory
    file_path = os.path.join(derivatives_dir, file_name)
    if os.path.exists(file_path):

        with open(file_path, 'r') as json_file:
            data_dict = json.load(json_file)

        print('A cached file containing the best frames of several scans has already been create. {}'.format(file_path))

        if entryname in data_dict.keys():
            print('The best frame for this file was previously calculated and will be used now.')
            return data_dict[entryname]

    else:
        print('A best frames cache file does not exist. It will be made now.')
        # Create the file if it doesn't exist
        with open(file_path, 'w') as file:
            # You can write initial content to the file if needed
            file.write("{}")
        print("File created.")
        data_dict = {}

    
    img = nib.load(in_file)
    numFrames = img.get_fdata().shape[-1]
    matrix = np.zeros((numFrames,numFrames))

    roi_basename = os.path.basename(in_file)[:-7] + '_vi'
    print('Note: the first iteration will take the longest.')
    for i in tqdm(range(numFrames)):

        v0 =  '{}{}.nii.gz'.format(roi_basename, i)
        if not os.path.exists(v0):
            v0 = pf.getVolume(in_file,i, v0)

        for j in range(i, numFrames): 
            v1 = '{}{}.nii.gz'.format(roi_basename, j)
            if not os.path.exists(v1):
                v1 = pf.getVolume(in_file,j, v1)

            sim = pf.getSimilarityBetweenVolumes(v0, v1, scheduleTXT)
            matrix[i,j] = sim
            matrix[j,i] = sim
    
    # clear temporary files in consideration for storage
    for filename in os.listdir('.'):
        if filename.startswith(roi_basename):
            os.remove(filename)

    column_means = np.mean(matrix, axis=0)
    bestVol = np.argmin(column_means).item()
    print('Volume number {} was identified as the best reference for motion correction.'.format(bestVol))

    data_dict[entryname] = bestVol

    print("This calculation will be saved in cache...")
    with open(file_path, 'w') as json_file:
        json.dump(data_dict, json_file)

    return bestVol


# Note: This function is used normalize the median of the data to 1000
#       Power et al normalized their mode to 1000, but we believe median is more stable.
def median_1000_normalization(in_file, mask_file=None):
    import numpy as np
    import nibabel as nib

    # Load the NIfTI image data
    img = nib.load(in_file)
    data = img.get_fdata()

    # only find the mode where there is brain tissue
    if not mask_file == None:
        print('Brain mask was provided.')
        mask_data = nib.load(mask_file).get_fdata()
        mask_4d   = mask_data[:, :, :, np.newaxis]
        numFrames = data.shape[-1]
        mask_4d   = np.tile(mask_4d, (1,1,1,numFrames))
        datamaskd = data[mask_4d == 1]
        median_value = np.median(datamaskd)
    else:
        median_value = np.median(data)

    print('Median value is {}'.format(median_value))

    # Perform mode 1000 normalization
    normalized_data = (data / median_value) * 1000

    # Create a new NIfTI image with the normalized data
    normalized_img = nib.Nifti1Image(normalized_data, img.affine, img.header)

    output_path = '{}_normalized.nii.gz'.format(in_file[:-7])
    # Save the normalized NIfTI image to the specified output path
    nib.save(normalized_img, output_path)

    return output_path


# Note: This function is used to calculate the DVARS values across the scan
# MOtion_DVARS_Subprocess
def MO_DVARS_Subprocess(in_file, mask=None):
    import os, sys
    import numpy as np
    import nibabel as nib
    import matplotlib.pyplot as plt

    threshold = 5.

    # Load the NIfTI file
    img = nib.load(in_file)
    data = img.get_fdata()

    # Broadcast the mask to all frames
    if not mask == None:
        mask_data = nib.load(mask).get_fdata()
        mask_4d   = mask_data[:, :, :, np.newaxis]
        numFrames = data.shape[-1]
        mask_4d   = np.tile(mask_4d, (1,1,1,numFrames))
        data      = np.multiply(data, mask_4d)

    # Calculate the temporal derivative of each voxel
    diff_data = np.diff(data, axis=-1)

    # Calculate the squared difference (DVARS) per frame
    dvars = np.sqrt(np.mean((diff_data ** 2),axis=(0, 1, 2)))

    outmetricfile = 'dvars_metrics.txt'
    outmetric_path = os.path.join(os.getcwd(), outmetricfile)
    # Save DVARS values to a text file
    with open(outmetric_path, 'w') as f:
        f.write('{}\n'.format(0)) #first frame has DVARS=0
        for dvar_value in dvars:
            f.write('{}\n'.format(dvar_value))


    outfilename = 'dvars_outliers.txt'
    outfile_path = os.path.join(os.getcwd(), outfilename)
    with open(outfile_path, 'w') as f:
        f.write('{}\n'.format(0)) #first frame has DVARS=0
        for dvar_value in dvars:
            printVal = 0
            if dvar_value > threshold:
                printVal = 1
            f.write('{}\n'.format(printVal))


    outplotfile = 'dvars_plot.png'
    outplot_path = os.path.join(os.getcwd(), outplotfile)
    frames = list(range(len(dvars)))
    plt.plot(frames, dvars, linestyle='-')
    # Customize the plot
    plt.xlabel('Frames')
    plt.ylabel('DVARS Values')
    plt.title('DVARS Over Frames')

    plt.savefig(outplot_path, dpi=300, bbox_inches='tight')


    return outfile_path, outmetric_path, outplot_path


def MO_FD_Subprocess(in_file, mask):
    import subprocess
    import os, sys
    from nipype.interfaces.fsl import MotionOutliers

    outfilename = 'fd_outliers.txt'
    outmetricfile = 'fd_metrics.txt'
    outfile_path = os.path.join(os.getcwd(), outfilename)
    outmetric_path = os.path.join(os.getcwd(), outmetricfile)

    mo = MotionOutliers()
    mo.inputs.in_file = in_file
    #mo.inputs.no_motion_correction = True  ## doesn't work with FD
    #mo.inputs.mask = mask
    mo.inputs.metric = 'fd'
    mo.inputs.threshold = 0.5
    mo.inputs.out_file = outfilename
    mo.inputs.out_metric_values = outmetricfile

    ##out = mo.run()
    cmdline = mo.cmdline.split(' ')
    y = subprocess.run(cmdline)
    print(y)

    files = [f for f in os.listdir('.') if os.path.isfile(f)]
    if outfilename not in files:
        with open(outfile_path, 'w'):
            pass
    
    return outfile_path, outmetric_path


#the artifact extraction function takes in the outliers file and the split BOLD image and removes the problematic frames
def ArtifactExtraction(split_images, dvars_outliers, fd_outliers):
    import os
    import numpy as np
    import json
    split_copy = split_images.copy()
    counter = 1
    fd_rejects = []
    dvars_rejects = []

    #opens both the art_detect and dvars outlier files and creates lists of the outlier frames
    if os.stat(dvars_outliers).st_size > 0:
        dvars_list = np.loadtxt(dvars_outliers)
        outs = np.where(dvars_list == 1)
        output_frames = list(outs[0])
        for frame in output_frames:
            dvars_rejects.append(frame)

        
    #finds the problematic frames from dvars and adds them to the list of problematic frames from art_detect
    if os.stat(fd_outliers).st_size > 0:
        fd_list = np.loadtxt(fd_outliers)
        outs = np.where(dvars_list == 1)
        output_frames = list(outs[0])
        for frame in output_frames:
            fd_rejects.append(frame)
    

    #removes duplicates from the list of problematic frames
    all_rejects = list(set(fd_rejects).union(dvars_rejects))

    #creates a dictionary with a list of the number and list of rejected frames
    reject_dict = {}
    reject_dict['Number of frames removed total'] = int(len(all_rejects))
    reject_dict['Number of frames removed by FD'] = int(len(fd_rejects))
    reject_dict['Number of frames removed by DVARS'] = int(len(dvars_rejects))
    reject_dict['Frames rejected by FD'] = [int(x) for x in set(fd_rejects)]
    reject_dict['Frames rejected by DVARS'] = [int(x) for x in set(dvars_rejects)]

    rejectionsFile = os.path.join(os.getcwd(),'rejections.json')
    with open(rejectionsFile, 'w') as r:
        json.dump(reject_dict, r, indent = 4)

    
    #removes the problematic frames from the BOLD
    for image in split_images:
        for outlier in all_rejects:
            test = '{:04d}'.format(int(outlier))
            if test in os.path.basename(image) and image in split_copy:
                split_copy.remove(image)
    return split_copy, rejectionsFile


# Note: takes in the image paths for the BOLD and template and runs the three 
# functions to output the average array, similarity matrix and mapping dictionary
def CalcSimMatrix (bold_path, template_path, maxSegVal): 
    import os
    import sys 
    import numpy as np
    import json
    sys.path.append('/data/')
    import pipeline_functions as pf
    
    
    #runs the data extraction functions
    avg_arr = pf.make_average_arr(bold_path,template_path, maxSegVal)
    sim_matrix = pf.build_sim_arr(avg_arr)
    
    #saves the extracted data files
    sim_matrix_file = os.path.join(os.getcwd(),'sim_matrix.csv')
    avg_matrix_file = os.path.join(os.getcwd(),'average_arr.csv')
    np.savetxt(sim_matrix_file, sim_matrix, delimiter=",")
    np.savetxt(avg_matrix_file, avg_arr, delimiter=",")
    
    # Note: this is not necessary and is only currently being written for backwards compatibility with later analyses
    # this can be safely removed for future projects
    mapping_dict = {i:i for i in range(0,maxSegVal+1)}
    mapping_dict_file = os.path.join(os.getcwd(),'mapping_dict.json')
    with open(mapping_dict_file, 'w') as fp:
        json.dump(mapping_dict, fp, indent = 4)
    
    #returns the files
    return avg_matrix_file, sim_matrix_file, mapping_dict_file

# Note: This function expands the original 6 motion parameters to 24 (R R**2 R' R'**2)
def expandMotionParameters(par_file):
    import numpy as np
    import os
    
    # Read the original .par file
    original_params = np.loadtxt(par_file)

    # Calculate the additional parameters
    squared_params = original_params**2
    derivatives = np.diff(original_params, axis=0)
    # Add one row back in
    derivatives = np.vstack((np.zeros(original_params.shape[1]), derivatives))
    squared_derivatives = derivatives**2

    # Combine all parameters
    expanded_params = np.hstack((original_params, squared_params, derivatives, squared_derivatives))

    # Write the expanded parameters to a new .par file
    outfile = os.path.join(os.getcwd(), 'expanded.par')
    np.savetxt(outfile, expanded_params, fmt='%.10g')
    
    return outfile


def regressHeadMotion(in_file, par_file):
    import subprocess
    import os, sys
    import nipype.interfaces.fsl as fsl 

    outT2VName = "design.mat"
    outT2VPath = os.path.join(os.getcwd(),outT2VName)
    t2v = fsl.Text2Vest()
    t2v.inputs.in_file = par_file
    t2v.inputs.out_file = outT2VName
    print(t2v.cmdline)
    t2v.run()
    
    outResidualName = 'res4d.nii.gz'
    outResidualPath = t2v_out = os.path.join(os.getcwd(),outResidualName)
    glm = fsl.GLM(in_file=in_file, design=outT2VName, demean = True, output_type='NIFTI')
    glm.inputs.out_res_name = outResidualName
    print(glm.cmdline)
    #out = glm.run()

    cmdline = glm.cmdline.split(' ')
    y = subprocess.run(cmdline)
    return outResidualPath


def plotMotionMetrics(fd_metrics_file, dvars_metrics_file):
    import os
    import matplotlib.pyplot as plt 

    with open(fd_metrics_file, "r") as file1:
        data1 = [float(line.strip()) for line in file1]

    with open(dvars_metrics_file, "r") as file2:
        data2 = [float(line.strip()) for line in file2]

    # Step 2: Create a plot
    fig, ax1 = plt.subplots(figsize=(10, 6))  # Set the figure size and create primary y-axis
    fig.patch.set_facecolor('white')  # Set the figure background color to white

    # Step 3: Plot the first dataset on the primary y-axis
    time = list(range(len(data1)))
    ax1.plot(time, data1, label='Framwise Displacement', color='b', alpha=1)

    # Customize the primary y-axis
    ax1.set_xlabel('Frames')
    ax1.set_ylabel('Framwise Displacement', color='b')
    ax1.tick_params(axis='y', labelcolor='b')

    # Create a secondary y-axis
    ax2 = ax1.twinx()

    # Step 4: Plot the second dataset on the secondary y-axis
    ax2.plot(time, data2, label='DVARS', color='r', alpha=1)

    # Customize the secondary y-axis
    ax2.set_ylabel('DVARS', color='r')
    ax2.tick_params(axis='y', labelcolor='r')

    # Add a legend for both datasets
    lines, labels = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax2.legend(lines + lines2, labels + labels2)
    
    # Add thresholds recommended by Power et al 2012
    ax1.axhline(y=0.5, color='blue', linestyle='dashed', alpha=0.5)
    ax2.axhline(y=5, color='red', linestyle='dashed', alpha=0.5)

    plt.title('Motion Metrics Across Frames')
    
    outfile_path = os.path.join(os.getcwd(), 'fd_dvars_plot.png')
    plt.savefig(outfile_path, dpi=300, bbox_inches='tight')
    
    return outfile_path


# def AntsNonLinRegistration(moving_image, fixed_image):
#     import subprocess
#     import os
#     from nipype.interfaces.ants import ANTS


#     # ANTS REGISTRATION IMPLEMENTATION
#     non_reg = ANTS()
#     non_reg.inputs.moving_image = moving_image
#     non_reg.inputs.fixed_image = fixed_image
#     non_reg.inputs.dimension=3
#     non_reg.inputs.metric=['CC',]
#     non_reg.inputs.metric_weight=[1.0,]
#     non_reg.inputs.radius=[5,]
#     non_reg.inputs.output_transform_prefix='ANTS_OUT'
#     non_reg.inputs.transformation_model='SyN'
#     non_reg.inputs.gradient_step_length=25
#     non_reg.inputs.number_of_time_steps=3
#     non_reg.inputs.delta_time=0.05
#     non_reg.inputs.regularization='Gauss'
#     non_reg.inputs.regularization_gradient_field_sigma=0
#     non_reg.inputs.regularization_deformation_field_sigma=3

#     if isTest:
#         non_reg.inputs.number_of_iterations=[[2,2,2,1]] #test parameters
#     else:
#         non_reg.inputs.number_of_iterations=[[100,100,100,50]]

#     # # non_reg.config = {'execution':{'remove_unnuecessary_outputs' : False}}

#     print("\n\nANTS COMMANDLINE: ")
#     og_cmdline = non_reg.cmdline
#     new_cmdline = og_cmdline.replace("SyN[25.,3.0,0.050]", "SyN[25.,3,0.050]")
#     print(new_cmdline)

#     out_warpedPath = os.path.join(os.getcwd(),'Warp.nii.gz')
#     return out_warpedPath 



# ******************************************************************************
# PIPELINE CREATION
# ******************************************************************************

#creates a pipeline
preproc = pe.Workflow(name='preproc')


#infosource iterates through the list and sends subject data into the pipeline one at a time
infosource = pe.Node(interface=util.IdentityInterface(fields=['subject']), name='infosource')
infosource.iterables = [('subject', subject_list_abs)]


#returns the directory of all input files to store outputs in
GenerateOutDir_node = pe.Node(interface=util.Function(input_names=['base_outputdir', 'image_path'], output_names=['out_dir'], function=GenerateOutDir), name='GenerateOutDir')
GenerateOutDir_node.inputs.base_outputdir = derivatives_dir
preproc.connect(infosource, 'subject', GenerateOutDir_node, 'image_path')

#the datasink node stores the outputs of all operations
datasink = pe.Node(nio.DataSink(parameterization=False), name='sinker')
preproc.connect(GenerateOutDir_node, 'out_dir', datasink, 'base_directory')


#the input node, which takes the input image from infosource and feeds it into the rest of the pipeline
input_node = pe.Node(interface=util.IdentityInterface(fields=['func']),name='input')
preproc.connect(infosource, 'subject', input_node, 'func')

reorient2std_node = pe.Node(interface=fsl.Reorient2Std(), name='reorient2std')
preproc.connect(input_node, 'func', reorient2std_node, 'in_file')
preproc.connect(reorient2std_node, 'out_file', datasink, OUTFOLDERNAME+'.@reorient')


#this node accesses the calculate_sigma function to take the input image and output its sigma value
sigma_value = pe.Node(interface=util.Function(input_names=['image_path', 'hp_frequency', 'lp_frequency'], output_names=['sigma_value_hp', 'sigma_value_lp'], function=calculate_sigma), name='calculate_sigmas')
sigma_value.inputs.hp_frequency=0.009
sigma_value.inputs.lp_frequency=0.08
preproc.connect(reorient2std_node, 'out_file', sigma_value, 'image_path')


#the template node feeds a standard brain into the linear registration node to be registered into BOLD space
template_feed = pe.Node(interface=util.IdentityInterface(fields=['template']), name='template_MNI')
template_feed.inputs.template = template_path


#the segment_feed node feeds a template segmentation into the linear registration node to be registered into BOLD space
segment_feed = pe.Node(interface=util.IdentityInterface(fields=['segment']), name='segment_AAL')
segment_feed.inputs.segment = segment_path

# # finds the best frame to use as a reference
bestRef_node = pe.Node(interface=util.Function(input_names=['in_file', 'scheduleTXT', 'derivatives_dir'], output_names=['bestReference'], function=findBestReference), name='findBestReference')
bestRef_node.inputs.scheduleTXT = scheduleTXT
bestRef_node.inputs.derivatives_dir = derivatives_dir
preproc.connect(input_node, 'func', bestRef_node, 'in_file')

#the MCFLIRT node motion corrects the image
motion_correct = pe.Node(interface=fsl.MCFLIRT(save_plots = True, save_rms= True), name='McFLIRT')
preproc.connect(reorient2std_node, 'out_file', motion_correct, 'in_file')
preproc.connect(bestRef_node, 'bestReference', motion_correct, 'ref_vol')

fslroi_node_2 = pe.Node(interface=fsl.ExtractROI(t_size=1), name = 'extractRoi_2')
preproc.connect(motion_correct, 'out_file', fslroi_node_2, 'in_file')
preproc.connect(bestRef_node, 'bestReference', fslroi_node_2, 't_min')

#the brain extraction node removes the nonbrain tissue and extracts the brain from the MRI image
brain_extract = pe.Node(interface=fsl.BET(frac=0.45, mask=True, robust=True), name='bet')
# functional=True,
preproc.connect(fslroi_node_2, 'roi_file', brain_extract, 'in_file')


#the apply bet node multiplies the brain mask to the entire BOLD image to apply the brain extraction
apply_bet = pe.Node(interface=fsl.BinaryMaths(operation = 'mul'), name = 'bet_apply')
preproc.connect(brain_extract, 'mask_file', apply_bet, 'operand_file')
# preproc.connect(brain_extract, 'mask_file', datasink, OUTFOLDERNAME+'.@mask')
preproc.connect(motion_correct, 'out_file', apply_bet, 'in_file')


# we normalize the brain to 1000 as recommended by Power et al, however we normalize to median instead of the mode
normalization_node = pe.Node(interface=util.Function(input_names=['in_file', 'mask_file'], output_names=['out_file'], function=median_1000_normalization), name='Median1000Normalization')
preproc.connect(apply_bet, 'out_file', normalization_node, 'in_file')
preproc.connect(brain_extract, 'mask_file', normalization_node, 'mask_file')



# calculate the framewise displacement between successive frames to remove jerks
fdnode = pe.Node(interface=util.Function(input_names=['in_file', 'mask'], output_names=['outfile', 'outmetric'], function=MO_FD_Subprocess), name='fd')
preproc.connect(apply_bet, 'out_file', fdnode, 'in_file')
preproc.connect(brain_extract, 'mask_file', fdnode, 'mask')



### CURRENTLY NOT USED ###
# #the average node takes the mean of the BOLD image over time to perform bias correction
# average = pe.Node(interface=fsl.MeanImage(), name='mean_image')
# preproc.connect(merge, 'merged_file', average, 'in_file')

# #the bias correct node takes the average frame of the BOLD and outputs a bias field that can be used for all other frames
# bias_correct = pe.Node(interface=fsl.FAST(bias_iters=2, output_biascorrected=True, output_biasfield=True), name='bias_correction')
# preproc.connect(average, 'out_file', bias_correct, 'in_files')

# #the apply bias node subtracts the bias field from the entire BOLD image to apply the bias correction
# apply_bias = pe.Node(interface=fsl.BinaryMaths(operation = 'sub'), name = 'bias_apply')
# preproc.connect(bias_correct, 'bias_field', apply_bias, 'operand_file')
# preproc.connect(merge, 'merged_file', apply_bias, 'in_file')

# expand 6 motion parameters to 24
expandParNode = pe.Node(interface=util.Function(input_names=['par_file'], output_names=['out_file'], function=expandMotionParameters), name='ExpandMotionParameters')
preproc.connect(motion_correct, 'par_file', expandParNode, 'par_file')

#this node will regress away the headmotion parameters and return the residuals
regressNode = pe.Node(interface=util.Function(input_names=['in_file', 'par_file'], output_names=['out_file'], function=regressHeadMotion), name='RegressMotionParameters')
preproc.connect(normalization_node, 'out_file', regressNode, 'in_file')
preproc.connect(expandParNode, 'out_file', regressNode, 'par_file')


#the bandpass filtering node filters out extraneous frequencies from the MRI image
band_pass = pe.Node(interface=fsl.TemporalFilter(), name='bandpass_filtering')
preproc.connect(sigma_value, 'sigma_value_hp', band_pass, 'highpass_sigma')
preproc.connect(sigma_value, 'sigma_value_lp', band_pass, 'lowpass_sigma')
preproc.connect(regressNode, 'out_file', band_pass, 'in_file')

#the smoothing node smooths the BOLD image. The 6mm fwhm informed by Power et al.
smooth = pe.Node(interface=fsl.Smooth(), name='smoothing')
smooth.inputs.fwhm = 6.0
preproc.connect(band_pass, 'out_file', smooth, 'in_file')


#a custom function to calculate dvars as indicated by Power et al. We noticed that FSL's motionoutlier renormalized before calculating dvars, which is not desirable here
dvarsnode = pe.Node(interface=util.Function(input_names=['in_file', 'mask'], output_names=['outfile', 'outmetric', 'outplot_path'], function=MO_DVARS_Subprocess), name='dvars')
preproc.connect(smooth, 'smoothed_file', dvarsnode, 'in_file')
preproc.connect(brain_extract, 'mask_file', dvarsnode, 'mask')


# a custom function to plot dvars values against fd values
plotmotionmetrics_node = pe.Node(interface=util.Function(input_names=['fd_metrics_file', 'dvars_metrics_file'], output_names=['outfile_path'], function=plotMotionMetrics), name='plot_fd_vs_dvars')
preproc.connect(fdnode, 'outmetric', plotmotionmetrics_node, 'fd_metrics_file')
preproc.connect(dvarsnode, 'outmetric', plotmotionmetrics_node, 'dvars_metrics_file')


#the split node splits the 4D BOLD image into its contituents 3D frames to allow certain timeframes to be removed
split = pe.Node(interface=fsl.Split(dimension='t'), name = 'splitter')
preproc.connect(smooth, 'smoothed_file', split, 'in_file')


#the artifact extract node removes the problematic frames as indicated by the artifact detection node
artifact_extract = pe.Node(interface=util.Function(input_names=['split_images', 'dvars_outliers', 'fd_outliers'], output_names=['extracted_images', 'rejectionsFile'], function=ArtifactExtraction), name='art_extract')
preproc.connect(split, 'out_files', artifact_extract, 'split_images')
preproc.connect(dvarsnode, 'outfile', artifact_extract, 'dvars_outliers')
preproc.connect(fdnode, 'outfile', artifact_extract, 'fd_outliers')


#the merge node concatenates the 3D frames of the BOLD into its original 4D state after the removal of troublesome frames
merge = pe.Node(interface=fsl.Merge(dimension = 't'), name = 'merger')
preproc.connect(artifact_extract, 'extracted_images', merge, 'in_files')

fslroi_node = pe.Node(interface=fsl.ExtractROI(t_size=1), name = 'extractRoi')
preproc.connect(apply_bet, 'out_file', fslroi_node, 'in_file')
preproc.connect(bestRef_node, 'bestReference', fslroi_node, 't_min')


#the linear registration node registers the standard brain into BOLD space using the BOLD image as reference and only using linear registration
lin_reg = pe.Node(interface=fsl.FLIRT(), name='linear_reg')
lin_reg.inputs.searchr_x = [-45,45]
lin_reg.inputs.searchr_y = [-45,45]
lin_reg.inputs.searchr_z = [-45,45]
preproc.connect(fslroi_node, 'roi_file', lin_reg, 'reference')
preproc.connect(template_feed, 'template', lin_reg, 'in_file')

#the apply_lin node applies the same linear registration as the standard brain to the template segmentation
apply_lin = pe.Node(interface=fsl.ApplyXFM(interp='nearestneighbour'), name='apply_linear')
preproc.connect(segment_feed, 'segment', apply_lin, 'in_file')
preproc.connect(fslroi_node, 'roi_file', apply_lin, 'reference')
preproc.connect(lin_reg, 'out_matrix_file', apply_lin, 'in_matrix_file')

# FORMER FSL REGISTRATION IMPLEMENTATION
#the non-linear registration node registers the linear registered brain to match the BOLD image using non-linear registration
non_reg = pe.Node(interface=fsl.FNIRT(), name='nonlinear_reg')
non_reg.inputs.in_fwhm            = [8, 4, 2, 2]
non_reg.inputs.subsampling_scheme = [4, 2, 1, 1]
non_reg.inputs.warp_resolution    = (6, 6, 6)
non_reg.inputs.max_nonlin_iter    = [2, 2, 2, 2]
# non_reg.inputs.max_nonlin_iter    = [20, 20, 10, 10]
# non_reg.inputs.max_nonlin_iter    = [100, 100, 50, 25]
preproc.connect(lin_reg, 'out_file', non_reg, 'in_file')
preproc.connect(fslroi_node, 'roi_file', non_reg, 'ref_file')

# FORMER FSL REGISTRATION IMPLEMENTATION
#the apply_non node applies the same non-linear registration as the standard brain to the template segmentation
apply_non = pe.Node(interface=fsl.ApplyWarp(interp='nn'), name='apply_nonlin')
preproc.connect(apply_lin, 'out_file', apply_non, 'in_file')
preproc.connect(fslroi_node, 'roi_file', apply_non, 'ref_file')
preproc.connect(non_reg, 'field_file', apply_non, 'field_file')

###############################################################################
# # # # ANTS REGISTRATION IMPLEMENTATION
# # # non_reg = pe.Node(interface=ants.Registration(), name='ants_Registration')
# non_reg = pe.Node(interface=util.Function(input_names=['moving_image', 'fixed_image'], output_names=['warped_file'], function=AntsNonLinRegistration), name='antsreg')
# preproc.connect(lin_reg, 'out_file', non_reg, 'moving_image')
# preproc.connect(fslroi_node, 'roi_file', non_reg, 'fixed_image')

# # # #the apply_non node applies the same non-linear registration as the standard brain to the template segmentation
# apply_non = pe.Node(interface=ants.ApplyTransforms(), name='apply_nonlin')
# apply_non.inputs.interpolation = 'NearestNeighbor'
# preproc.connect(apply_lin, 'out_file', apply_non, 'input_image')
# preproc.connect(fslroi_node, 'roi_file', apply_non, 'reference_image')
# preproc.connect(non_reg, 'warped_file', apply_non, 'transforms')
###############################################################################

rename_node = pe.Node(interface=util.Rename(), name='Rename')
rename_node.inputs.keep_ext = True
rename_node.inputs.format_string = 'final_preprocessed_output'
preproc.connect(merge, 'merged_file',rename_node, 'in_file')
preproc.connect(rename_node, 'out_file',datasink, OUTFOLDERNAME+'.@final_out')


#the data extraction node takes in the BOLD and template images and extracts the necessary data (average voxel intensity per region, a similarity matrix, and a mapping dictionary)
CalcSimMatrix_node = pe.Node(interface=util.Function(input_names=['bold_path', 'template_path', 'maxSegVal'], output_names=['avg_arr_file', 'sim_matrix_file', 'mapping_dict_file'], function=CalcSimMatrix), name='CalcSimMatrix')
CalcSimMatrix_node.inputs.maxSegVal = MAX_SEGMENT_VAL
preproc.connect(merge, 'merged_file', CalcSimMatrix_node, 'bold_path')
preproc.connect(apply_non, 'out_file', CalcSimMatrix_node, 'template_path') # FSL Registation implementation
# preproc.connect(apply_non, 'output_image', CalcSimMatrix_node, 'template_path')  # ANTS registration implementation



# # ******************************************************************************
# # IF MEMORY IS PLENTIFUL, THEN SAVE EVERYTHING
SAVE_INTERMEDIATES = True
if(SAVE_INTERMEDIATES):
    # preproc.connect(segment_feed, 'segment', datasink, OUTFOLDERNAME+'.@OGSeg')
    # preproc.connect(motion_correct, 'out_file', datasink, OUTFOLDERNAME+'.@mcf_out')
    # preproc.connect(motion_correct, 'par_file', datasink, OUTFOLDERNAME+'.@mcf_par')
    # preproc.connect(motion_correct, 'rms_files', datasink, OUTFOLDERNAME+'.@mcf_rms')
    # preproc.connect(brain_extract, 'out_file', datasink, OUTFOLDERNAME+'.@be_out')
    preproc.connect(apply_bet, 'out_file', datasink, OUTFOLDERNAME+'.@applybe_out')
    # preproc.connect(normalization_node, 'out_file', datasink, OUTFOLDERNAME+'.@normalization')
    # preproc.connect(artifact, 'outlier_files', datasink, OUTFOLDERNAME+'.@artdet_outs')
    # preproc.connect(calcOutliers, 'out_file', datasink, OUTFOLDERNAME+'.@calcFDOuts_outs')
    # preproc.connect(artifact_extract, 'rejectionsFile', datasink, OUTFOLDERNAME+'.@rejects_summ')
    # preproc.connect(merge, 'merged_file', datasink, OUTFOLDERNAME+'.@merge_out')
    # preproc.connect(bias_correct, 'bias_field', datasink, OUTFOLDERNAME+'.@bias')
    # preproc.connect(regressNode, 'out_file', datasink, OUTFOLDERNAME+'.@residual_out')
    # preproc.connect(apply_bias, 'out_file', datasink, OUTFOLDERNAME+'.@appbias_out')
    # preproc.connect(band_pass, 'out_file', datasink, OUTFOLDERNAME+'.@bandpass_out')
    # preproc.connect(smooth, 'smoothed_file', datasink, OUTFOLDERNAME+'.@smooth_out')
    preproc.connect(lin_reg, 'out_file', datasink, OUTFOLDERNAME+'.@lin_out')
    preproc.connect(lin_reg, 'out_matrix_file', datasink, OUTFOLDERNAME+'.@lin_mat')
    preproc.connect(non_reg, 'warped_file', datasink, OUTFOLDERNAME+'.@nlin_out')
    preproc.connect(non_reg, 'field_file', datasink, OUTFOLDERNAME+'.@nlin_mat')
    preproc.connect(apply_lin, 'out_file', datasink, OUTFOLDERNAME+'.@app_lin_out')
    preproc.connect(apply_non, 'out_file', datasink, OUTFOLDERNAME+'.@app_nlin_out')
    # preproc.connect(fdnode, 'outfile', datasink, OUTFOLDERNAME+'.@fd_out')
    # preproc.connect(fdnode, 'outmetric', datasink, OUTFOLDERNAME+'.@fd_metrics')
    # preproc.connect(dvarsnode, 'outfile', datasink, OUTFOLDERNAME+'.@dvars_out')
    # preproc.connect(dvarsnode, 'outmetric', datasink, OUTFOLDERNAME+'.@dvars_metrics')
    # preproc.connect(dvarsnode, 'outplot_path', datasink, OUTFOLDERNAME+'.@dvars_plot')
    preproc.connect(plotmotionmetrics_node, 'outfile_path', datasink, OUTFOLDERNAME+'.@fdvsdvars_plot')
    preproc.connect(CalcSimMatrix_node, 'avg_arr_file', datasink, OUTFOLDERNAME+'.@avgBoldSigPerRegion')
    preproc.connect(CalcSimMatrix_node, 'sim_matrix_file', datasink, OUTFOLDERNAME+'.@similarityMatrix')
    preproc.connect(CalcSimMatrix_node, 'mapping_dict_file', datasink, OUTFOLDERNAME+'.@MappingDict')
# # ******************************************************************************


# # ******************************************************************************
# # PIPELINE RUN
# # ******************************************************************************

#creates a workflow diagram (IN THE CURRENT WORKING DIRECTORY)
preproc.write_graph()

# # preproc.run(plugin='MultiProc', plugin_args={'n_procs': 8, 'memory_gb': 20})
preproc.run()

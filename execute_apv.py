import json
import git
import os
import subprocess
import shutil
import logging
import concurrent.futures
import argparse

format = "%(asctime)s: %(message)s"
logging.basicConfig(format=format, level=logging.INFO, datefmt="%H:%M:%S")

config_file = "config.json"
apv_metadata_file = "apv-metadata.json"
android_prepare_vendor_repo = "https://github.com/AOSPAlliance/android-prepare-vendor.git"
temp_out_dir = "out"

def execute_apv(device, build_id, temp_out, metadata_only, cleanup):
    logging.info("device {}: running android-prepare-vendor with build_id {}".format(device, build_id))
    result = subprocess.run(["./out/android-prepare-vendor/execute-all.sh", "-d", device, "-b", build_id, "-o", temp_out])
    if result.returncode != 0:
        raise Exception("android-prepare-vendor returned exit code {} for device {}", result.returncode, device)

    generated_out = "out/{}/{}/vendor/google_devices/{}".format(device, build_id.lower(), device)
    destination = "{}".format(device)

    logging.info("device {}: removing existing destination directory {}".format(device, destination))
    shutil.rmtree(destination, ignore_errors=True)

    if metadata_only:
        os.makedirs(destination, exist_ok=False)
        logging.info("device {}: copying only metadata files from {} to {}".format(device, generated_out, destination))
        shutil.copy("{}/build_id.txt".format(generated_out), "{}/build_id.txt".format(destination))
        shutil.copy("{}/file_signatures.txt".format(generated_out), "{}/file_signatures.txt".format(destination))
        shutil.copy("{}/vendor-board-info.txt".format(generated_out), "{}/vendor-board-info.txt".format(destination))
    else:
        logging.info("device {}: moving directory from {} to {}".format(device, generated_out, destination))
        shutil.move(generated_out, destination)

    if cleanup:
        device_temp_out = "{}/{}".format(temp_out, device)
        logging.info("device {}: cleaning up temp output directory: {}".format(device, device_temp_out))
        shutil.rmtree(device_temp_out, ignore_errors = False)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-t', '--threads', default=1, help='how many threads to use', type=int)
    parser.add_argument('-m', '--metadata', default=False, help='only copy metadata txt files', action='store_true')
    parser.add_argument('-c', '--cleanup', default=True, help='cleanup output directory data for each device', action='store_true')
    parser.add_argument('-r', '--repo', default=android_prepare_vendor_repo, help='android prepare vendor git repo', type=str)
    args = parser.parse_args()

    logging.info("creating output directory: {}".format(temp_out_dir))
    os.makedirs(temp_out_dir, exist_ok=True)

    temp_out_dir_apv = "{}/android-prepare-vendor".format(temp_out_dir)
    shutil.rmtree("{}".format(temp_out_dir_apv), ignore_errors=True)
    logging.info("cloning {} to {}".format(args.repo, temp_out_dir_apv))
    repo = git.Repo.clone_from(args.repo, temp_out_dir_apv)

    logging.info("using android-prepare-vendor latest commit: {} - {}".format(str(repo.head.commit.hexsha), str(repo.head.commit.message)))
    apv_metadata = {
        'repo': android_prepare_vendor_repo,
        'commit': str(repo.head.commit.hexsha),
        'message': str(repo.head.commit.message)
    }
    apv_metadata_json_output = json.dumps(apv_metadata, indent=2)
    with open(apv_metadata_file, "w") as outfile:
        outfile.writelines(apv_metadata_json_output)

    with open(config_file) as f:
        config = json.load(f)
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as executor:
            future_apv = {executor.submit(execute_apv, device, config['devices'][device]['build_id'], temp_out_dir, args.metadata, args.cleanup): device for device in config['devices']}
            for future in concurrent.futures.as_completed(future_apv):
                data = future.result()

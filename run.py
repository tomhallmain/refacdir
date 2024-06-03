from glob import glob
import sys

from refacdir.batch import BatchJob

def main(test=True, skip_confirm=False):
    configurations = sorted(glob("configs/*.yaml", recursive=False))
    batch_job = BatchJob(configurations=configurations, test=test, skip_confirm=skip_confirm)
    batch_job.run()
    batch_job.log_results()


if __name__ == "__main__":
    test = False # TODO update to False
    skip_confirm = False
    if len(sys.argv) > 1:
        if "test".startswith(sys.argv[1].lower()):
            test = True
        if "skip_confirm".startswith(sys.argv[1].lower()):
            skip_confirm = True
    main(test=test, skip_confirm=skip_confirm)

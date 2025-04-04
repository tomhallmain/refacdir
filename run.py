import getopt
import sys

from refacdir.batch import BatchArgs, BatchJob
from refacdir.utils.utils import Utils


help_text = """Edit configuration YAML files in configs directory to configure file management batch actions.

Once desired configurations are set, run with:
python run.py [args]

    -h, --help
        Print this help text

    -v, --verbose
        Run in verbose mode

    -t, --test
        Run file management actions in test mode, without taking any action

    -s, --skip-confirm
        Run file management actions without confirming

        --configs
        Specify comma-separated list of config files to run

    -o, --only-observers
        Load configs but only run any Directory Observer actions defined in them
"""


def main(args):
    batch_job = BatchJob(args)
    batch_job.run()
    batch_job.log_results()


if __name__ == "__main__":
    batch_args = BatchArgs()

    try:
        opts, args = getopt.getopt(sys.argv[1:], ":hstvo", [
                "help",
                "verbose",
                "test",
                "skip-confirm",
                "only-observers",
                "configs=",
                ])
    except getopt.GetoptError as err:
        # print help information and exit:
        print(err)  # will print something like "option -a not recognized"
        print(help_text)
        sys.exit(2)

    for o, a in opts:
        # basic options
        if o in ("-h", "--help"):
            print(help_text)
            exit()
        elif o in ("-v", "--verbose"):
            batch_args.verbose = True
        elif o in ("-t", "--test"):
            batch_args.test = True
        elif o in ("-s", "--skip-confirm"):
            batch_args.skip_confirm = True
        elif o in ("-c", "--configs"):
            string_list = a.strip()
            if string_list == "":
                raise Exception("Expected config file paths list not found")
            try:
                batch_args.configs = Utils.get_list_from_string(string_list)
            except Exception as e:
                raise Exception(f"Invalid config list provided: {e}")
        elif o in ("-o", "--only-observers"):
            batch_args.only_observers = True


    main(batch_args)


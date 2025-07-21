# pattern-service

Hi there! We're excited to have you as a contributor.

## Table of contents

- [pattern-service](#pattern-service)
  - [Table of contents](#table-of-contents)
  - [Things to know prior to submitting code](#things-to-know-prior-to-submitting-code)
    - [Build and Run the Development Environment](#build-and-run-the-development-environment)
      - [Clone the repo](#clone-the-repo)
      - [Configure python environment](#configure-python-environment)
      - [Configure and run the application](#configure-and-run-the-application)

## Things to know prior to submitting code

- All code submissions are done through pull requests against the `main` branch.
- Take care to make sure no merge commits are in the submission, and use `git rebase` vs `git merge` for this reason.
- If collaborating with someone else on the same branch, consider using `--force-with-lease` instead of `--force`. This will prevent you from accidentally overwriting commits pushed by someone else. For more information, see [git push docs](https://git-scm.com/docs/git-push#git-push---force-with-leaseltrefnamegt).
- We ask all of our community members and contributors to adhere to the [Ansible code of conduct](http://docs.ansible.com/ansible/latest/community/code_of_conduct.html). If you have questions, or need assistance, please reach out to our community team at [codeofconduct@ansible.com](mailto:codeofconduct@ansible.com)
- This repository uses a`pre-commit`, configuration, so ensure that you install pre-commit globally for your user, or by using pipx.

### Build and Run the Development Environment

#### Clone the repo

If you have not already done so, you will need to clone, or create a local copy, of the [pattern-service repository](https://github.com/ansible/pattern-service).
For more on how to clone the repo, view [git clone help](https://git-scm.com/docs/git-clone).
Once you have a local copy, run the commands in the following sections from the root of the project tree.

#### Configure python environment

Create python virtual environment using one of the below commands:

`virtualenv --python 3.x /path/to/virtual_env` or `python3.x -m venv /path/to/virtual_env`

Set the virtual environment

`source /path/to/virtualenv/bin/activate/`

Install required python modules

`pip install -r ./requirements-all.txt`

#### Configure and run the application

`python manage.py migrate && python manage.py runserver`

The application can be reached in your browser at `https://localhost:8000/`

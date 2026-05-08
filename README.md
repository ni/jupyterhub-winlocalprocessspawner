# WinLocalProcessSpawner

WinLocalProcessSpawner spawns single-user servers as local Windows processes. It uses the authentication credentials stored on the **auth_token** field of [auth_state](http://jupyterhub.readthedocs.io/en/latest/reference/authenticators.html). It is the Authenticator's responsability to store the Windows authentication token on the **auth_token**. If Jupyterhub was launched with "Local System" privileges, the **auth_token** will have a user profile associated with it, which will allow the spawner to extract the per-user APPDATA and USERPROFILE environment variables. Those variables are used to set the jupyter runtime directory and the CWD respectively.

For an example of these architecture, check the [WinAuthenticator](https://github.com/ni/jupyterhub-winauthenticator).

# Local development
- Install `dev-requirements.txt` by running `pip install -r dev-requirements.txt` in your **Python 3.8** virtual environment.
  This contains both dependencies required for this project, as well as testing + linting dependencies.
  The `dev-requirements.txt` file also installs the current project as an editable package, via `-e .`
- Tests can be run using `pytest .`
- Linting can be run using `ni-python-styleguide lint winlocalprocessspawner/` and `ni-python-styleguide lint tests`.

# Installation

Currenty, there is no pip package, so you need to install the winlocalprocessspawner by cloning the repo.

```
git clone https://github.com/ni/jupyterhub-winlocalprocessspawner.git
cd jupyterhub-winlocalprocessspawner
pip3 install -e
```

# Usage

To enable, add the following to your jupyterhub file:

```
c.JupyterHub.spawner_class = 'winlocalprocessspawner.WinLocalProcessSpawner'
```



# Golf Env

Golf environment for training RL agents.

## Dependencies

- numpy
- cv2
- matplotlib
- scipy
- imageio

## Download

```shell
# in a git repository clone as submodule
$ cd <PROJECT_DIR>
$ git submodule add https://github.com/jinkim31/golf_env.git
```

## Demo code

```python
from golf_env.src import golf_env
from golf_env.src import heuristic_agent


def main():
    env = golf_env.GolfEnv('sejong')
    state = env.reset()
    agent = heuristic_agent.HeuristicAgent()

    while True:
        state, reward, termination = env.step(agent.step(state))
        if termination:
            break
            
    env.plot()


if __name__ == '__main__':
    main()

```
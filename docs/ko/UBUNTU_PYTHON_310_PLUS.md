# Ubuntu에서 Python 3.10+ 설치하기

이 문서는 Ubuntu 환경에 기본 설치된 Python 버전이 낮아서 `dormammu`를 바로
설치할 수 없는 경우를 위한 운영 가이드입니다.

`dormammu`는 Python `3.10+`를 기준으로 합니다. Ubuntu에서는 배포판 버전에
따라 기본 Python 버전이 다를 수 있으므로, 시스템 기본 `python3`를 억지로
바꾸기보다 필요한 버전을 별도로 설치한 뒤 `python3.10` 이상 인터프리터를
명시적으로
사용하는 쪽이 안전합니다.

## 먼저 확인할 것

현재 Python 버전을 먼저 확인합니다.

```bash
python3 --version
```

이미 `Python 3.10` 이상이 보이면 이 문서는 건너뛰고 일반 설치 절차를
진행하면 됩니다.

## 빠른 판단 기준

2026-04 기준으로 설치 방향은 보통 아래처럼 나뉩니다.

- Ubuntu 24.04 이상:
  기본 Python이 이미 `3.12` 이상인 경우가 많으므로 추가 설치 없이
  진행해도 됩니다.
- Ubuntu 22.04:
  기본 Python `3.10`이 보통 이미 요구사항을 만족하므로 추가 설치 없이
  진행해도 됩니다.
- Ubuntu 20.04 이하:
  기본 Python이 `3.10` 미만인 경우가 많으므로 `python3.10` 패키지를
  별도로 설치하거나, 가능하면 OS 업그레이드를 먼저 검토하는 편이
  좋습니다.

## Ubuntu 22.04 이상에서 설치

먼저 현재 기본 Python이 요구사항을 만족하는지 확인합니다.

```bash
python3 --version
```

`Python 3.10` 이상이면 아래처럼 바로 가상환경을 만들면 됩니다.

```bash
python3 -m venv .venv
. .venv/bin/activate
python --version
```

만약 기본 `python3`에 `venv` 모듈이 없다면 아래 패키지를 설치합니다.

```bash
sudo apt update
sudo apt install -y python3-venv
```

## Ubuntu 20.04 계열에서 설치

Ubuntu 20.04처럼 기본 저장소에 `python3.10`이 없는 환경에서는 PPA가
필요할 수 있습니다.

먼저 `add-apt-repository` 명령이 없을 때를 대비해 관련 패키지를 설치합니다.

```bash
sudo apt update
sudo apt install -y software-properties-common
```

그 다음 `deadsnakes` PPA를 추가하고 패키지 목록을 다시 갱신합니다.

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
```

이후 Python 3.10과 가상환경 패키지를 설치합니다.

```bash
sudo apt install -y python3.10 python3.10-venv python3.10-dev
```

설치 확인:

```bash
python3.10 --version
```

## 가상환경 만들기

시스템 Python을 바꾸지 말고, 프로젝트마다 원하는 Python 버전으로
가상환경을 만드는 방식을 권장합니다.

```bash
python3.10 -m venv .venv
. .venv/bin/activate
python --version
```

여기서 `python --version` 결과가 `3.10+`로 나오면 정상입니다.

## `dormammu` 설치하기

저장소에서 바로 설치할 때는 `scripts/install.sh`가 `PYTHON` 환경변수를
읽으므로, 아래처럼 원하는 Python을 명시할 수 있습니다.

```bash
PYTHON=python3.10 ./scripts/install.sh
```

수동 설치를 원하면 아래처럼 진행합니다.

```bash
python3.10 -m venv .venv
. .venv/bin/activate
pip install -e .
```

설치 후에는 doctor로 환경을 확인합니다.

```bash
.venv/bin/dormammu doctor --repo-root . --agent-cli /path/to/agent-cli
```

## 자주 막히는 지점

### `python3.10-venv`가 없어서 `venv` 생성이 실패할 때

아래 패키지가 빠졌는지 확인합니다.

```bash
sudo apt install -y python3.10-venv
```

### `add-apt-repository: command not found`

아래 패키지를 먼저 설치합니다.

```bash
sudo apt install -y software-properties-common
```

### `python3 --version`은 여전히 낮게 나오는데 괜찮은가

괜찮습니다. 중요한 것은 시스템 기본 `python3`를 바꾸는 것이 아니라,
`python3.10` 이상 인터프리터로 가상환경을 만들고 그 환경에서 `dormammu`를 실행하는
것입니다.

## 권장하지 않는 방법

- `/usr/bin/python3`를 직접 바꾸는 것
- `update-alternatives`로 시스템 기본 Python을 강제로 교체하는 것
- 프로젝트 가상환경 없이 시스템 전역에만 의존하는 것

Ubuntu의 많은 시스템 도구는 배포판이 기대하는 기본 Python에 의존하므로,
시스템 기본 인터프리터를 바꾸면 다른 명령이 깨질 수 있습니다.

## 참고 흐름

가장 안전한 기본 흐름은 아래와 같습니다.

```bash
python3 --version
python3.10 --version
python3.10 -m venv .venv
. .venv/bin/activate
pip install -e .
.venv/bin/dormammu doctor --repo-root . --agent-cli /path/to/agent-cli
```

이 흐름으로 준비되면 이후에는 일반적인 `dormammu` 설치/실행 가이드를
따르면 됩니다.

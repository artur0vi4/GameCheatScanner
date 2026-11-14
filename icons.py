"""Иконки интерфейса (PNG, base64) и app-логотип.
Самодостаточный модуль: все иконки вшиты как base64, поэтому
PyInstaller упаковывает их без --add-data. PhotoImage создаётся
один раз и кэшируется на всё время жизни окна."""
from __future__ import annotations
import tkinter as tk

_cache: dict = {}

ICONS_B64 = {
    'search': (
        'iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAYAAABWzo5XAAABS0lEQVR4nJWTvUoDQRSFz91NQE1h'
        'lyKJgthoI9jamMpSfAxtBB/AwsLCFxAfxE6sBLEQLMSkiZ3iC4hJ4fpZeEfGdce4F4b5ubPfnD13'
        'xlQKIJOUSfqQZN4KM6O8NxkOSeWsFgRYBI6BG+AS2AVm/wWLIH1gzFeMgBcf3wFtwJKqgcw3LACv'
        'wD2wHuV2gHfg2udJUNP7Ez991ed5pHTfc/2QqwLl3t8Cj6W13FsPKIBDX2+UObHMN0kzbmjwIuRb'
        'Pp4kbP7xa3suf7tizxkwAZaTPrnRBrS8OgVwACwBa8CpH/AMdJIeBZj3beCK3xGuwRDoVcEshoVn'
        'AGxK2nBPziWNJV1IWpE0lLRlZk9AbmZFUllCdQ8YuLJBpCz5rELZG96y6Dp0S7DuVFgVPFL24LAR'
        'MF8LVIJ1HHYENJNVnAILz2au9sd/wL6L8wn8YbmrlPs14wAAAABJRU5ErkJggg=='
    ),
    'funnel': (
        'iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAYAAABWzo5XAAAA70lEQVR4nM2SQUoDQRBFX09iQBC3'
        '3kDwEILb7DyAJxByBG8ieCDP4NYDGERJMvPcVEMlOtMYECwoPt38+v2rquFfhjpT50fWLgCK2gFn'
        'wBNwBWyBrlUf+QHcAS+EEOql+u7v4rZ2VO1VsWv1Te3VbWDOnboJkfs9kdTrPPBGXUdRf+Cgiqxy'
        'zU+DOwlcpuIhcBf4kLlTW6jOVuGgtjWoj5WjlsZC9mb2nJyt1fO4/yYytmZDrM93wOnY46P/pZQy'
        'AIcvD2P81m+uH4+ERwl1ydVsitgS2kQCfE4RJ1eoXgCLegReY3Z/Fy1HJXOm3HwBxOwkXUwRZ8gA'
        'AAAASUVORK5CYII='
    ),
    'plus': (
        'iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAYAAABWzo5XAAABMElEQVR4nKWUsU7EMBBE35wjRAHd'
        'USAKRMNfUEDPJ/BBSNDQIPFDVAiJ4v7gRI3oIMlQZB2c010SwUiWpfVmdma9sZiA7QQIaCR5Kv/f'
        '0IQaAZfAAfAiaW1bs5UFAbaT7bU73ESs2vbNYgbvB9AAX2NJA/asBJBt6KynWIrzvFNaHBAVBw7i'
        'tqwjybbbbT3qiaJKtqogS0VuilGoQi1ATyrbSVJj+wp4BNoNwlNgD3gHPiNWR5EnSfe2q4rfEVgC'
        '55uSCxzHKnGWCyrPhe0T4CIsZfIFcBcED8BzxOrYV5LebE/fvu1VzNH1WN5ms3Nzy2bnnMMYxioU'
        'QdfsdkAU3a8zadg18B3xRlJtG0mZqMecyV5Gwf1Z1nbAwC1wBLxmOzOK/x2jzwj0f3t+2Haq+QEu'
        '7Zt5ME0m4gAAAABJRU5ErkJggg=='
    ),
    'pen': (
        'iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAYAAABWzo5XAAAAwUlEQVR4nMWSMQ7CMAxF7bYIJjY4'
        'A0zdWIEbsbNwBC6AOAorx0ECJgqPxREWoiUplbAUWZbj528nIh2ZphYAmYggIqqqj1ZdDVIbx0Jy'
        '8xOgB0zbQArzC+AMHMyvgSw0SYFcgTsv20aBHGT+BjkCG8s17ylcMCUX4GaQHaCWa351B1kapAqQ'
        'kI8ZR+2MgZPbR4DkX5V4RVawspH2yRAHKoEBMAOKoDQWoPbZSmAU3bkG1geGDpwljfNJ3U+KOoP8'
        '3Z6u1xJiEXNVTgAAAABJRU5ErkJggg=='
    ),
    'snowflake': (
        'iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAYAAABWzo5XAAABvUlEQVR4nH2UP08VURDFz+x7LAlR'
        'gxQUPixsILGxM/43Jn4Bukeo7fgAgCR8A2KMdsZPoNHGP4V5BSFiKKjUisRGCiiwNBTys9hzk2F5'
        'j01udnbunLNn5s7cUOsBQtI9SccRseNvRQTAbUkh6VtEnLSxmWTa73fAK9tdoGt7Fdi1PTWMIIAa'
        '2AR2gAOgb3/HK4D73tsCBsZEm6wLXAWWgF/Atv1VUrRM86w7tnOGqEX6wICFpHgG+Ae8OQ9Y5RRT'
        'nY6AMX9/AP4CvZJuxmayUovaac5Z1TLwyPaSY8czWSH4CDweoXTNKg6BwTll+BzAnKQNSbUkJFVq'
        'ekWSxiXdtf1d0oH38DqRNCnpSSVpQtJ1SVcMyKdwIdn5B4XssqRrknoCfgDPR8h+67T2gE8jYlaA'
        'nwIm7SjNV7t3+i7wInDHdt97tWPLaV8qrMXR8YldBP4AX9PeF2AfGPOqMrYMaVvuSyu4kdTO2rc2'
        'JD6UAjtu+6cGPEsqS/O9AI5pxqiHR+cUo/Me0AzkIfCQs0M7D/ymGexNhg2tCaf83gVWbedr5DXw'
        '3vZ0xg6rTyXpliQiYpvTF9tNNU26FRFk3H+r2j7O45QVrAAAAABJRU5ErkJggg=='
    ),
    'trash': (
        'iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAYAAABWzo5XAAABJklEQVR4nK2UQUrEQBBFXyWtCIKC'
        'FxA9gDfwGp7Jo3gEF+IVdDMwgiADsxBGxo2CSpLvYqrG2JOOLqag6crvqv+L36FhS2GRSKoyXMAR'
        'cOLYApgBlZ+tCs26P1UkXesnniXtlmqTJDMzSToF9gP3/binfgicS1oCna8WmJpZh6Ta1e80Hl0B'
        'PwjlULwC7oE94MJ9Wnvoeece3QBz4A34KvlSS1oUpmh8neV9VUaw4xPOAu5rADXwCbxISpLSBpGZ'
        'tUDj15koR+31DSuzfxNl3xPf+/9ITPfkE5mZKW9cD+b7+8hEH2a2YXBOFLEcwEL9NRMdJZoMYEE0'
        'HeotmZqAxldE5HWpoaSasvPIH/5DFLf0CFxmZ61Pc5vVbjdsCJRklP1rh96gb9ADzrm+MhcOAAAA'
        'AElFTkSuQmCC'
    ),
    'refresh': (
        'iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAYAAABWzo5XAAABVElEQVR4nK2UPU7DQBCF39gWCVHE'
        'AYgo09BAAVKoAAE1R6Clo6KFC1BQcA4aao4QFAlRgRB/DR0dEgZ/FMxGTrJxAmIka72zM2/emx1b'
        '+iezqkMgkZSEraTCzJgaHUgcZBz4ZEZAYmaFv7cldSTVJV2ZWXc4pkqKgAXgnFHrAZ0qZkGOAfPA'
        'syceA6vAErAPvLp/w3PSGFDq6wWQA+uRmBZwDzwB2UgvS5LaXvHI9/UQDNTct+kxZ2UlASjzdQ8o'
        'gOXhai47ARol6afuT4cbVtfPvOSxPvpNJZKa7jqQdGhmX5k7wlV2PXDNzG6AGvBRZiWpIelW0puk'
        'E0m9vrSS1gy4Bl6AVoxVuaeVh8CK638EdoBm6GEkJx1gEwHbAh4cMAfugNkgLzzl3IFKZlb4+F8C'
        'i5J2JW1LmpE0J+nd46b7cKMTO8HG/kaceh/QzD5/C/4n+waRL2Ku4ZWlEgAAAABJRU5ErkJggg=='
    ),
    'info': (
        'iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAYAAABWzo5XAAABiUlEQVR4nI2UvUoDURCFZ3bjTyEi'
        'NqIWWguClYWQUvAXRK0M2PsWghh8AMFCwQcQtLKwUbGwCLZBUgiBlKKglSFmP4vMxXF3jd5i587O'
        'mTNzz51dlS4LiEQkMjcREVSVbjkZAiPJi8V57zUPqKpt20+KyJTh6qpaTWN+6yQ2OwNckV1VYK1b'
        'Z55kC2gDH8ARsAqsALtAwwjLQYI8TRSYBppABRi32BlQs30/cGxkpUxngRm4Ad6AEfN7gVPgHhh2'
        '+AfgBRi0BtSTTFilQ/P7zM4B67bvMbtp2PC+0Hl0nCUgARasSiC6BT4BdR2NGvYgFPBiFcw2U/fw'
        'LiKvqUFspXIkEpEAeJLOvBQtKXRAwLhBnbb4Y/rWFIiBGlAHeswvAHemR+xkuABawJi/LD9Dy5Z0'
        '4ooUgQ3n7xhmz+f6rgJZ2YAVoAQM2RgsAucWu7RTRP4S8si2gWfy137QypPkfbSRqibAgIjMi8is'
        'E/ZaVRtB1z9/KZlz/yOWPd93gopILD/HIFHVJA//BQMa765RjlKQAAAAAElFTkSuQmCC'
    ),
}

LOGO_B64 = (
    'iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAADGElEQVR4nO2Vy4scVRTGf+feW909'
    'PXGcScQXKoiIkGAwEDIKguBrcKUylC4iJJiAqyiuXCRQXQnZuAkkG8WFzqJdZBb+AboQFwqBKImM'
    '4sQEI5LNqDPBpKe6+t57XFR3ZzoZTCbgLh8cLqeKe853HvUV3MFNIKOuig4fim40mKJSBV3nbpap'
    '+S//JqFHiOoaf+TFgd068eAEtviTq/m8lFmmppWjrez6Siu0WmirheS5RIBje3RyBcjnZGWQWNJU'
    '7fy8hENv6d7E8mFQjIElDczmbfnpVvi/n+rYpgafW8NzKOIDXzw8zjuXHiAIQLZbt4pjQRWiQuKg'
    '7LFsLOdiQFB0WEN/SMZCjAgRVWGqkfB46UEVJppw+SrvHm3LCQcQhbss4ANBBNMtUSNM9TrsqjfB'
    'mH7gflN9D/wq2ASSGsQIRUkUQVTx3mMNbAEwfVZRteImgohg6k10eobgGoSyRyg9oQyEziph8l5C'
    'eoBw/6OETocQlSiC6c9UECQq/loCwNqqCTHCP8vgHPLqPqyz2CuXsSJYY7BlgX1iB/apZ7Hbn6n8'
    'boHRNYspghjBAbgsU7P5b84urfBlYnmp1iRs3YmdmKpasW0a7nsELixADDA2Dqe+qkgsnoVGEx7b'
    'BhfPge+hzmFXS/4yjs8GFZj3TkgX+IUIk/egr+2HF2ZBDLw4Cy+/2Z+vggh4D6e/geUleHoG3j4I'
    'z78ORQd1Dgme5XxOfhtpEcrdSR29dBEO74OPW2AtfJTB8Q+GpQ/P5iaoN+D3Rfj1Rzi/AC6BGFGE'
    'ZpapqxJ8Pdy+7wQEJYig3QL9+XR1ikH7SzC04FFXQ/84j35yBF08A0kd7wyCcCbPCWmqVhSVFgh7'
    'qMXAqfExnrxSABG6RcVSTNWetZDBJyGVRYWaA4346JnO2/xwMsUYQZQM8jkpguGV1S5tAx0MvjFO'
    'UIgxElVHLQ7OSIwRL+A18m0ZmMnb8n2WIW/MS1ijMSoDBc3260OuICnWFYb14RIk/1QuQCWUA30a'
    'garKyVTtBuLegPS6++uq5Mak+hryHL2d/8gd/L/4F+Aob8aBLVGrAAAAAElFTkSuQmCC'
)

NAMES = tuple(ICONS_B64) + ("logo",)

def load(root: tk.Misc) -> dict[str, tk.PhotoImage]:
    """Вернуть словарь PhotoImage {name: img}. Создаёт один раз, кэш на root."""
    if _cache:
        return _cache
    d = {n: tk.PhotoImage(data=b) for n, b in ICONS_B64.items()}
    d["logo"] = tk.PhotoImage(data=LOGO_B64)
    _cache.update(d)
    return d

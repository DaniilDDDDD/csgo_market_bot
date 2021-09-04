import asyncio
items_before = [
    {
        'id': 1,
        'name': 'one'
    },
    {
        'id': 2,
        'name': 'two'
    }
]

items_after = [
    {
        'id': 1,
        'name': 'one'
    },
    None
]


# print([item for item in items_after if item is not None] )

def main():
    async def f():
        print('Hello world!)')


    asyncio.run(f())


if __name__ == '__main__':
    main()
